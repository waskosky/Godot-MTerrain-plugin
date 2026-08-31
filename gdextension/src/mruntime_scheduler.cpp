#include "mruntime_scheduler.h"

#include <algorithm>
#include <chrono>
#include <cmath>

#include <godot_cpp/variant/packed_string_array.hpp>

#include "mgrid.h"

namespace {
constexpr int32_t MAX_TILE_SIDE = 67;
constexpr int32_t MAX_TILE_SAMPLES = 4489;
constexpr int32_t MAX_TILE_REGIONS = 16;
constexpr int32_t MIN_STEP_SAMPLE_OPS = 128;
constexpr int32_t MAX_STEP_SAMPLE_OPS = 16384;
constexpr int32_t MAX_STEP_REGION_OPS = 16;
constexpr int32_t MAX_COMPLETED_RESULTS = 256;

class ScopedRuntimeTiming {
    uint64_t& total_usec;
    uint64_t& longest_usec;
    uint64_t& invocation_count;
    std::chrono::steady_clock::time_point started;

public:
    ScopedRuntimeTiming(
        uint64_t& p_total_usec,
        uint64_t& p_longest_usec,
        uint64_t& p_invocation_count
    ) :
        total_usec(p_total_usec),
        longest_usec(p_longest_usec),
        invocation_count(p_invocation_count),
        started(std::chrono::steady_clock::now()) {
    }

    ~ScopedRuntimeTiming() {
        const uint64_t elapsed_usec =
            (uint64_t)std::chrono::duration_cast<std::chrono::microseconds>(
                std::chrono::steady_clock::now()-started
            ).count();
        total_usec += elapsed_usec;
        longest_usec = std::max(longest_usec, elapsed_usec);
        invocation_count++;
    }
};
}

MRuntimeScheduler::MRuntimeScheduler(MGrid* p_grid) : grid(p_grid) {
}

Dictionary MRuntimeScheduler::fail(const String& p_code, const String& p_message) const {
    Dictionary result;
    result["ok"] = false;
    result["api_version"] = 2;
    result["code"] = p_code;
    result["message"] = p_message;
    return result;
}

Dictionary MRuntimeScheduler::configure_limits(const Dictionary& p_limits) {
    if(!pending.is_empty() || !collision_operations.is_empty()){
        return fail(
            "work_in_progress",
            "Runtime limits cannot change while tile or collision work is pending"
        );
    }
    PackedStringArray accepted_keys;
    accepted_keys.push_back("max_pending_work");
    accepted_keys.push_back("max_resident_tiles");
    accepted_keys.push_back("max_resident_regions");
    accepted_keys.push_back("max_collision_regions");
    accepted_keys.push_back("max_estimated_region_bytes");
    const Array supplied_keys = p_limits.keys();
    for(int32_t index=0; index < supplied_keys.size(); index++){
        const Variant key_value = supplied_keys[index];
        if(key_value.get_type() != Variant::STRING &&
            key_value.get_type() != Variant::STRING_NAME){
            return fail("invalid_limit_key", "Runtime limit keys must be strings");
        }
        const String key = key_value;
        if(!accepted_keys.has(key)){
            return fail("unknown_limit_key", "Unknown runtime limit key: "+key);
        }
        if(p_limits[key].get_type() != Variant::INT){
            return fail("invalid_limit_type", "Runtime limit values must be integers");
        }
    }
    const int32_t requested_pending = (int32_t)p_limits.get("max_pending_work", max_pending_work);
    const int32_t requested_tiles = (int32_t)p_limits.get("max_resident_tiles", max_resident_tiles);
    const int32_t requested_regions = (int32_t)p_limits.get("max_resident_regions", max_resident_regions);
    const int32_t requested_collision = (int32_t)p_limits.get("max_collision_regions", max_collision_regions);
    const int64_t requested_bytes = (int64_t)p_limits.get(
        "max_estimated_region_bytes",
        max_estimated_region_bytes
    );
    if(requested_pending < 1 || requested_pending > 128){
        return fail("invalid_pending_limit", "max_pending_work must be between 1 and 128");
    }
    if(requested_tiles < 1 || requested_tiles > 64){
        return fail("invalid_tile_limit", "max_resident_tiles must be between 1 and 64");
    }
    if(requested_regions < 1 || requested_regions > 64){
        return fail("invalid_region_limit", "max_resident_regions must be between 1 and 64");
    }
    if(requested_collision < 0 || requested_collision > 16 || requested_collision > requested_regions){
        return fail(
            "invalid_collision_limit",
            "max_collision_regions must be between 0 and 16 and cannot exceed max_resident_regions"
        );
    }
    if(requested_bytes < 1024LL*1024LL || requested_bytes > 1024LL*1024LL*1024LL){
        return fail(
            "invalid_memory_limit",
            "max_estimated_region_bytes must be between 1 MiB and 1 GiB"
        );
    }
    if(resident.size() > requested_tiles){
        return fail("resident_tile_limit_in_use", "The requested tile limit is below current residency");
    }
    if(runtime_owned_region_count_with(Vector<int32_t>()) > requested_regions){
        return fail("resident_region_limit_in_use", "The requested region limit is below current residency");
    }
    if(desired_collision_regions.size() > requested_collision){
        return fail(
            "collision_limit_in_use",
            "The requested collision limit is below current collision ownership"
        );
    }
    if(estimated_loaded_region_bytes() > requested_bytes){
        return fail(
            "memory_limit_in_use",
            "The requested memory limit is below current loaded-region usage"
        );
    }
    max_pending_work = requested_pending;
    max_resident_tiles = requested_tiles;
    max_resident_regions = requested_regions;
    max_collision_regions = requested_collision;
    max_estimated_region_bytes = requested_bytes;
    Dictionary result;
    result["ok"] = true;
    result["code"] = "ok";
    result["limits"] = snapshot().get("limits", Dictionary());
    return result;
}

Dictionary MRuntimeScheduler::validate_and_build_work(
    const String& p_work_key,
    int64_t p_revision,
    int32_t p_priority,
    int32_t p_start_x,
    int32_t p_start_y,
    int32_t p_width,
    int32_t p_height,
    const PackedFloat32Array& p_heights_m,
    bool p_update_collision,
    TileWork& r_work
) const {
    if(grid == nullptr || !grid->is_created()){
        return fail("grid_not_created", "Create the terrain grid before queueing a height tile");
    }
    if(p_work_key.is_empty() || p_work_key.length() > 128){
        return fail("invalid_work_key", "work_key must contain between 1 and 128 characters");
    }
    if(p_revision < 0){
        return fail("invalid_revision", "revision must be non-negative");
    }
    if(p_priority < -1000 || p_priority > 1000){
        return fail("invalid_priority", "priority must be between -1000 and 1000");
    }
    if(p_start_x < 0 || p_start_y < 0){
        return fail("negative_origin", "Height tile coordinates must be non-negative");
    }
    if(p_width <= 0 || p_height <= 0){
        return fail("invalid_dimensions", "Height tile dimensions must be positive");
    }
    if(p_width > MAX_TILE_SIDE || p_height > MAX_TILE_SIDE){
        return fail("tile_too_large", "Height tiles are limited to 67 by 67 samples");
    }
    const int64_t sample_count = (int64_t)p_width*(int64_t)p_height;
    if(sample_count > MAX_TILE_SAMPLES || p_heights_m.size() != sample_count){
        return fail("sample_count_mismatch", "Height sample count does not match the bounded tile dimensions");
    }
    const int64_t end_x_exclusive = (int64_t)p_start_x + (int64_t)p_width;
    const int64_t end_y_exclusive = (int64_t)p_start_y + (int64_t)p_height;
    if(end_x_exclusive > grid->pixel_width || end_y_exclusive > grid->pixel_height){
        return fail("tile_out_of_bounds", "Height tile extends beyond the configured terrain grid");
    }
    PackedFloat32Array staged;
    staged.resize((int32_t)sample_count);
    for(int32_t index=0; index < sample_count; index++){
        const float value = p_heights_m[index];
        if(!std::isfinite(value)){
            return fail("non_finite_height", "Height tiles cannot contain NaN or infinity");
        }
        staged.set(index, value);
    }

    auto overlap_bounds = [
        p_start_x,
        p_start_y,
        p_width,
        p_height
    ](
        int32_t p_other_x,
        int32_t p_other_y,
        int32_t p_other_width,
        int32_t p_other_height,
        int32_t& r_left,
        int32_t& r_top,
        int32_t& r_right,
        int32_t& r_bottom
    ) -> bool {
        r_left = MAX(p_start_x, p_other_x);
        r_top = MAX(p_start_y, p_other_y);
        r_right = MIN(p_start_x+p_width, p_other_x+p_other_width)-1;
        r_bottom = MIN(p_start_y+p_height, p_other_y+p_other_height)-1;
        return r_left <= r_right && r_top <= r_bottom;
    };
    auto staged_overlap_matches = [&staged, &overlap_bounds, p_start_x,
        p_start_y, p_width, p_height](const TileWork& p_other) -> bool {
        int32_t left = 0;
        int32_t top = 0;
        int32_t right = -1;
        int32_t bottom = -1;
        if(!overlap_bounds(
            p_other.start_x,
            p_other.start_y,
            p_other.width,
            p_other.height,
            left,
            top,
            right,
            bottom
        )){
            return true;
        }
        const bool vertical_shared_edge = left == right &&
            (left == p_start_x || left == p_start_x+p_width-1) &&
            (left == p_other.start_x ||
                left == p_other.start_x+p_other.width-1);
        const bool horizontal_shared_edge = top == bottom &&
            (top == p_start_y || top == p_start_y+p_height-1) &&
            (top == p_other.start_y ||
                top == p_other.start_y+p_other.height-1);
        if(!vertical_shared_edge && !horizontal_shared_edge){
            return true;
        }
        for(int32_t y=top; y <= bottom; y++){
            for(int32_t x=left; x <= right; x++){
                const int32_t candidate_index =
                    (y-p_start_y)*p_width+(x-p_start_x);
                const int32_t other_index =
                    (y-p_other.start_y)*p_other.width+(x-p_other.start_x);
                if(staged[candidate_index] != p_other.heights[other_index]){
                    return false;
                }
            }
        }
        return true;
    };
    for(const TileWork& other : pending){
        if(other.key == p_work_key){
            continue;
        }
        if(!staged_overlap_matches(other) ||
            (other.replacement != nullptr &&
                !staged_overlap_matches(*other.replacement))){
            return fail(
                "shared_sample_mismatch",
                "Overlapping height tiles with different work keys must supply identical shared samples"
            );
        }
    }
    for(const ResidentTile& other : resident){
        if(other.key == p_work_key){
            continue;
        }
        int32_t left = 0;
        int32_t top = 0;
        int32_t right = -1;
        int32_t bottom = -1;
        if(!overlap_bounds(
            other.start_x,
            other.start_y,
            other.width,
            other.height,
            left,
            top,
            right,
            bottom
        )){
            continue;
        }
        const bool vertical_shared_edge = left == right &&
            (left == p_start_x || left == p_start_x+p_width-1) &&
            (left == other.start_x || left == other.start_x+other.width-1);
        const bool horizontal_shared_edge = top == bottom &&
            (top == p_start_y || top == p_start_y+p_height-1) &&
            (top == other.start_y || top == other.start_y+other.height-1);
        if(!vertical_shared_edge && !horizontal_shared_edge){
            continue;
        }
        for(int32_t y=top; y <= bottom; y++){
            for(int32_t x=left; x <= right; x++){
                const int32_t candidate_index =
                    (y-p_start_y)*p_width+(x-p_start_x);
                if(staged[candidate_index] !=
                    grid->get_height_by_pixel((uint32_t)x, (uint32_t)y)){
                    return fail(
                        "shared_sample_mismatch",
                        "Overlapping height tiles with different work keys must supply identical shared samples"
                    );
                }
            }
        }
    }

    const uint32_t normal_left = (uint32_t)(p_start_x > 0 ? p_start_x-1 : 0);
    const uint32_t normal_top = (uint32_t)(p_start_y > 0 ? p_start_y-1 : 0);
    const uint32_t normal_right = (uint32_t)MIN(end_x_exclusive, grid->pixel_width-1);
    const uint32_t normal_bottom = (uint32_t)MIN(end_y_exclusive, grid->pixel_height-1);
    const uint32_t resident_left = normal_left > 0 ? normal_left-1 : 0;
    const uint32_t resident_top = normal_top > 0 ? normal_top-1 : 0;
    const uint32_t resident_right = MIN(normal_right+1, grid->pixel_width-1);
    const uint32_t resident_bottom = MIN(normal_bottom+1, grid->pixel_height-1);
    Vector<int32_t> region_ids = grid->runtime_get_region_ids_for_pixel_bounds(
        resident_left,
        resident_right,
        resident_top,
        resident_bottom
    );
    if(region_ids.is_empty()){
        return fail("tile_region_plan_empty", "Height tile did not resolve to a terrain region");
    }
    if(region_ids.size() > MAX_TILE_REGIONS || region_ids.size() > max_resident_regions){
        return fail(
            "tile_region_limit_exceeded",
            "Height and normal halo touch more regions than the bounded runtime permits"
        );
    }
    if(p_update_collision && region_ids.size() > max_collision_regions){
        return fail(
            "collision_region_limit_exceeded",
            "Height tile collision touches more regions than the configured collision ceiling"
        );
    }

    r_work.key = p_work_key;
    r_work.revision = p_revision;
    r_work.priority = p_priority;
    r_work.start_x = p_start_x;
    r_work.start_y = p_start_y;
    r_work.width = p_width;
    r_work.height = p_height;
    r_work.normal_left = normal_left;
    r_work.normal_right = normal_right;
    r_work.normal_top = normal_top;
    r_work.normal_bottom = normal_bottom;
    r_work.heights = staged;
    r_work.previous_heights.resize((int32_t)sample_count);
    r_work.region_ids = region_ids;
    r_work.normal_row = (int32_t)normal_top;
    r_work.update_collision = p_update_collision;

    Dictionary result;
    result["ok"] = true;
    result["code"] = "ok";
    return result;
}

int32_t MRuntimeScheduler::find_pending(const String& p_key) const {
    for(int32_t index=0; index < pending.size(); index++){
        if(pending[index].key == p_key){
            return index;
        }
    }
    return -1;
}

int32_t MRuntimeScheduler::find_resident(const String& p_key) const {
    for(int32_t index=0; index < resident.size(); index++){
        if(resident[index].key == p_key){
            return index;
        }
    }
    return -1;
}

int32_t MRuntimeScheduler::choose_pending() const {
    for(int32_t index=0; index < pending.size(); index++){
        if(pending[index].cancelled){
            return index;
        }
    }
    // Once sample preflight begins, keep that work item selected until it
    // installs. Its saved rollback values must not straddle another tile's
    // mutations, even when a higher-priority request arrives later.
    for(int32_t index=0; index < pending.size(); index++){
        const TileWork& candidate = pending[index];
        if(candidate.phase > WORK_PREFLIGHT ||
            (candidate.phase == WORK_PREFLIGHT && candidate.sample_cursor > 0)){
            return index;
        }
    }
    int32_t best = -1;
    for(int32_t index=0; index < pending.size(); index++){
        const TileWork& candidate = pending[index];
        if(best < 0 ||
            (candidate.priority > pending[best].priority) ||
            (candidate.priority == pending[best].priority && candidate.sequence < pending[best].sequence)){
            best = index;
        }
    }
    return best;
}

int32_t MRuntimeScheduler::choose_oldest_resident(const String& p_excluded_key) const {
    int32_t oldest = -1;
    for(int32_t index=0; index < resident.size(); index++){
        if(resident[index].key == p_excluded_key){
            continue;
        }
        if(oldest < 0 || resident[index].last_touch < resident[oldest].last_touch ||
            (resident[index].last_touch == resident[oldest].last_touch && resident[index].key < resident[oldest].key)){
            oldest = index;
        }
    }
    return oldest;
}

int32_t MRuntimeScheduler::runtime_owned_region_count_with(const Vector<int32_t>& p_candidate) const {
    Vector<int32_t> ids;
    auto append_unique = [&ids](int32_t p_id) {
        if(ids.find(p_id) < 0){
            ids.push_back(p_id);
        }
    };
    for(const ResidentTile& tile : resident){
        for(int32_t region_id : tile.region_ids){
            append_unique(region_id);
        }
    }
    for(const TileWork& work : pending){
        if(work.cancelled && work.write_cursor <= 0){
            // A cancelled active item no longer owns regions, but its staged
            // successor still reserves its bounded residency plan.
        } else {
            for(int32_t region_id : work.region_ids){
                append_unique(region_id);
            }
        }
        if(work.replacement != nullptr){
            for(int32_t region_id : work.replacement->region_ids){
                append_unique(region_id);
            }
        }
    }
    for(int32_t region_id : desired_collision_regions){
        append_unique(region_id);
    }
    for(int32_t region_id : p_candidate){
        append_unique(region_id);
    }
    return ids.size();
}

int32_t MRuntimeScheduler::nonresident_owned_region_count_with(
    const Vector<int32_t>& p_candidate,
    int32_t p_excluded_pending_index,
    int32_t p_excluded_replacement_index
) const {
    Vector<int32_t> ids;
    auto append_unique = [&ids](int32_t p_id) {
        if(ids.find(p_id) < 0){
            ids.push_back(p_id);
        }
    };
    for(int32_t index=0; index < pending.size(); index++){
        if(index == p_excluded_pending_index){
            continue;
        }
        const TileWork& work = pending[index];
        if(!(work.cancelled && work.write_cursor <= 0)){
            for(int32_t region_id : work.region_ids){
                append_unique(region_id);
            }
        }
        if(index != p_excluded_replacement_index &&
            work.replacement != nullptr){
            for(int32_t region_id : work.replacement->region_ids){
                append_unique(region_id);
            }
        }
    }
    for(int32_t region_id : desired_collision_regions){
        append_unique(region_id);
    }
    for(int32_t region_id : p_candidate){
        append_unique(region_id);
    }
    return ids.size();
}

int64_t MRuntimeScheduler::estimated_loaded_region_bytes() const {
    if(grid == nullptr || !grid->is_created()){
        return 0;
    }
    int64_t result = 0;
    for(int32_t region_id : managed_loaded_region_ids()){
        result += (int64_t)grid->runtime_estimated_region_bytes(region_id);
    }
    return result;
}

Vector<int32_t> MRuntimeScheduler::managed_loaded_region_ids() const {
    Vector<int32_t> ids;
    if(grid == nullptr || !grid->is_created()){
        return ids;
    }
    auto append_loaded = [this,&ids](int32_t p_region_id) {
        if(ids.find(p_region_id) < 0 && grid->runtime_region_is_loaded(p_region_id)){
            ids.push_back(p_region_id);
        }
    };
    for(const ResidentTile& tile : resident){
        for(int32_t region_id : tile.region_ids){
            append_loaded(region_id);
        }
    }
    for(const TileWork& work : pending){
        for(int32_t region_id : work.region_ids){
            append_loaded(region_id);
        }
        if(work.replacement != nullptr){
            for(int32_t region_id : work.replacement->region_ids){
                append_loaded(region_id);
            }
        }
    }
    for(int32_t region_id : desired_collision_regions){
        append_loaded(region_id);
    }
    for(int32_t region_id : active_collision_regions){
        append_loaded(region_id);
    }
    for(const RegionOperation& operation : collision_operations){
        append_loaded(operation.region_id);
    }
    for(int32_t region_id : pending_evictions){
        append_loaded(region_id);
    }
    ids.sort();
    return ids;
}

int32_t MRuntimeScheduler::managed_loaded_region_count() const {
    return managed_loaded_region_ids().size();
}

bool MRuntimeScheduler::region_needed(int32_t p_region_id) const {
    for(const ResidentTile& tile : resident){
        if(tile.region_ids.find(p_region_id) >= 0){
            return true;
        }
    }
    for(const TileWork& work : pending){
        if((!work.cancelled || work.write_cursor > 0) &&
            work.region_ids.find(p_region_id) >= 0){
            return true;
        }
        if(work.replacement != nullptr &&
            work.replacement->region_ids.find(p_region_id) >= 0){
            return true;
        }
    }
    return collision_region_desired(p_region_id);
}

bool MRuntimeScheduler::collision_region_desired(int32_t p_region_id) const {
    return desired_collision_regions.find(p_region_id) >= 0;
}

void MRuntimeScheduler::schedule_region_eviction_if_unowned(int32_t p_region_id) {
    if(region_needed(p_region_id) || pending_evictions.find(p_region_id) >= 0){
        return;
    }
    pending_evictions.push_back(p_region_id);
    pending_evictions.sort();
}

void MRuntimeScheduler::schedule_resident_release(int32_t p_resident_index) {
    if(p_resident_index < 0 || p_resident_index >= resident.size()){
        return;
    }
    const Vector<int32_t> released_regions = resident[p_resident_index].region_ids;
    resident.remove_at(p_resident_index);
    evicted_tile_count++;
    for(int32_t region_id : released_regions){
        schedule_region_eviction_if_unowned(region_id);
    }
}

Dictionary MRuntimeScheduler::queue_height_tile(
    const String& p_work_key,
    int64_t p_revision,
    int32_t p_priority,
    int32_t p_start_x,
    int32_t p_start_y,
    int32_t p_width,
    int32_t p_height,
    const PackedFloat32Array& p_heights_m,
    bool p_update_collision
) {
    TileWork work;
    Dictionary validation = validate_and_build_work(
        p_work_key,
        p_revision,
        p_priority,
        p_start_x,
        p_start_y,
        p_width,
        p_height,
        p_heights_m,
        p_update_collision,
        work
    );
    if(!(bool)validation.get("ok", false)){
        return validation;
    }

    const int32_t pending_index = find_pending(p_work_key);
    const TileWork* latest_pending = nullptr;
    if(pending_index >= 0){
        const TileWork& existing = pending[pending_index];
        latest_pending = existing.replacement != nullptr
            ? existing.replacement.get()
            : &existing;
        if(p_revision < latest_pending->revision){
            return fail("stale_revision", "A newer revision is already pending for this work key");
        }
        if(p_revision == latest_pending->revision){
            if(existing.cancelled && existing.replacement == nullptr){
                return fail(
                    "revision_cancelling",
                    "The matching revision is already queued for cancellation"
                );
            }
            Dictionary result;
            result["ok"] = true;
            result["code"] = "ok";
            result["status"] = "already_queued";
            result["work_key"] = p_work_key;
            result["revision"] = p_revision;
            return result;
        }
    }
    const int32_t resident_index = find_resident(p_work_key);
    if(resident_index >= 0 && p_revision <= resident[resident_index].revision){
        if(p_revision == resident[resident_index].revision){
            resident.write[resident_index].last_touch = ++sequence;
            Dictionary result;
            result["ok"] = true;
            result["code"] = "ok";
            result["status"] = "already_resident";
            result["work_key"] = p_work_key;
            result["revision"] = p_revision;
            return result;
        }
        return fail("stale_revision", "A newer revision is already resident for this work key");
    }

    if(pending_index < 0 && pending.size() >= max_pending_work){
        return fail("pending_work_limit", "The bounded runtime work queue is full");
    }
    const bool replaces_prewrite = pending_index >= 0 &&
        !pending[pending_index].cancelled &&
        pending[pending_index].phase < WORK_WRITE_HEIGHTS;
    const int32_t excluded_pending_index = replaces_prewrite ? pending_index : -1;
    Vector<int32_t> non_evictable_regions = work.region_ids;
    if(resident_index >= 0){
        for(int32_t region_id : resident[resident_index].region_ids){
            if(non_evictable_regions.find(region_id) < 0){
                non_evictable_regions.push_back(region_id);
            }
        }
    }
    if(nonresident_owned_region_count_with(
        non_evictable_regions,
        excluded_pending_index,
        pending_index
    ) > max_resident_regions){
        return fail(
            "residency_budget_exceeded",
            "Pending work, collision ownership, and this tile exceed the resident-region ceiling"
        );
    }

    work.sequence = ++sequence;
    if(pending_index < 0){
        pending.push_back(work);
    } else if(replaces_prewrite){
        const TileWork existing = pending[pending_index];
        Dictionary coalesced = fail(
            "coalesced",
            "Runtime work was superseded by a newer revision before mutation"
        );
        coalesced["work_key"] = existing.key;
        coalesced["revision"] = existing.revision;
        coalesced["status"] = "coalesced";
        push_result(coalesced);
        pending.write[pending_index] = work;
        for(int32_t region_id : existing.region_ids){
            schedule_region_eviction_if_unowned(region_id);
        }
        coalesced_count++;
    } else {
        TileWork& existing = pending.write[pending_index];
        if(existing.replacement != nullptr){
            const Vector<int32_t> replaced_regions =
                existing.replacement->region_ids;
            Dictionary coalesced = fail(
                "coalesced",
                "A staged replacement was superseded by a newer revision"
            );
            coalesced["work_key"] = existing.replacement->key;
            coalesced["revision"] = existing.replacement->revision;
            coalesced["status"] = "coalesced";
            push_result(coalesced);
            coalesced_count++;
            existing.replacement = std::make_shared<TileWork>(work);
            for(int32_t region_id : replaced_regions){
                schedule_region_eviction_if_unowned(region_id);
            }
        } else {
            existing.replacement = std::make_shared<TileWork>(work);
        }
        if(!existing.cancelled){
            existing.cancelled = true;
            existing.superseded = true;
            coalesced_count++;
        }
    }

    while((resident.size() >= max_resident_tiles && resident_index < 0) ||
        runtime_owned_region_count_with(work.region_ids) > max_resident_regions){
        const int32_t eviction_index = choose_oldest_resident(p_work_key);
        if(eviction_index < 0){
            return fail("residency_budget_exceeded", "No resident tile can be evicted for this request");
        }
        schedule_resident_release(eviction_index);
    }
    queued_count++;
    Dictionary result;
    result["ok"] = true;
    result["code"] = "ok";
    result["status"] = "queued";
    result["work_key"] = p_work_key;
    result["revision"] = p_revision;
    result["affected_regions"] = work.region_ids.size();
    result["staged_samples"] = work.heights.size();
    return result;
}

void MRuntimeScheduler::push_result(const Dictionary& p_result) {
    completed_results.push_back(p_result.duplicate(true));
    while(completed_results.size() > MAX_COMPLETED_RESULTS){
        completed_results.remove_at(0);
    }
}

void MRuntimeScheduler::finish_work(int32_t p_pending_index, const Dictionary& p_result) {
    push_result(p_result);
    const Vector<int32_t> released_regions = pending[p_pending_index].region_ids;
    pending.remove_at(p_pending_index);
    for(int32_t region_id : released_regions){
        schedule_region_eviction_if_unowned(region_id);
    }
}

void MRuntimeScheduler::finish_cancelled_work(
    int32_t p_pending_index,
    const Dictionary& p_result
) {
    push_result(p_result);
    const Vector<int32_t> released_regions = pending[p_pending_index].region_ids;
    const std::shared_ptr<TileWork> replacement =
        pending[p_pending_index].replacement;
    if(replacement != nullptr){
        pending.write[p_pending_index] = *replacement;
    } else {
        pending.remove_at(p_pending_index);
    }
    for(int32_t region_id : released_regions){
        schedule_region_eviction_if_unowned(region_id);
    }
}

void MRuntimeScheduler::install_resident(const TileWork& p_work) {
    const int32_t existing_index = find_resident(p_work.key);
    if(existing_index >= 0){
        const Vector<int32_t> previous_regions = resident[existing_index].region_ids;
        resident.remove_at(existing_index);
        for(int32_t region_id : previous_regions){
            schedule_region_eviction_if_unowned(region_id);
        }
    }
    ResidentTile tile;
    tile.key = p_work.key;
    tile.revision = p_work.revision;
    tile.last_touch = ++sequence;
    tile.start_x = p_work.start_x;
    tile.start_y = p_work.start_y;
    tile.width = p_work.width;
    tile.height = p_work.height;
    tile.region_ids = p_work.region_ids;
    resident.push_back(tile);
    for(int32_t region_id : p_work.region_ids){
        const int32_t eviction_index = pending_evictions.find(region_id);
        if(eviction_index >= 0){
            pending_evictions.remove_at(eviction_index);
        }
    }
}

void MRuntimeScheduler::queue_collision_refresh(
    const Vector<int32_t>& p_region_ids,
    bool p_admit_if_unfocused
) {
    // Compatibility callers historically requested collision on the tile
    // update itself. Until an explicit focus is supplied, each such tile moves
    // the bounded collision set. An explicit focus remains the residency owner
    // (including an intentional empty set) and tile updates only refresh its
    // intersecting regions.
    if(!collision_focus_explicit && p_admit_if_unfocused){
        collision_revision = MAX((int64_t)0, collision_revision+1);
        desired_collision_regions = p_region_ids;
        collision_operations.clear();
        collision_error.clear();
        for(int32_t region_id : active_collision_regions){
            if(grid->runtime_region_has_collision(region_id) &&
                desired_collision_regions.find(region_id) < 0){
                RegionOperation disable;
                disable.region_id = region_id;
                disable.revision = collision_revision;
                disable.enable = false;
                collision_operations.push_back(disable);
            }
        }
        for(int32_t region_id : desired_collision_regions){
            RegionOperation enable;
            enable.region_id = region_id;
            enable.revision = collision_revision;
            enable.enable = true;
            enable.refresh = grid->runtime_region_has_collision(region_id);
            collision_operations.push_back(enable);
        }
        return;
    }
    for(int32_t region_id : p_region_ids){
        if(!collision_region_desired(region_id)){
            continue;
        }
        if(!p_admit_if_unfocused &&
            !grid->runtime_region_has_collision(region_id)){
            continue;
        }
        for(int32_t index=collision_operations.size()-1; index >= 0; index--){
            if(collision_operations[index].region_id == region_id){
                collision_operations.remove_at(index);
            }
        }
        RegionOperation operation;
        operation.region_id = region_id;
        operation.revision = collision_revision;
        operation.enable = true;
        operation.refresh = grid->runtime_region_has_collision(region_id);
        collision_operations.push_back(operation);
    }
}

bool MRuntimeScheduler::process_one_eviction() {
    if(pending_evictions.is_empty()){
        return false;
    }
    const int32_t region_id = pending_evictions[0];
    pending_evictions.remove_at(0);
    if(region_needed(region_id)){
        return true;
    }
    if(grid->runtime_unload_region(region_id)){
        region_unload_count++;
    }
    return true;
}

bool MRuntimeScheduler::process_one_collision_operation() {
    if(collision_operations.is_empty()){
        return false;
    }
    const RegionOperation operation = collision_operations[0];
    collision_operations.remove_at(0);
    if(operation.revision != collision_revision){
        return true;
    }
    if(operation.enable && !grid->runtime_region_is_loaded(operation.region_id)){
        if(!grid->runtime_load_region(operation.region_id)){
            collision_error = fail(
                "collision_region_load_failed",
                "A collision region could not be loaded"
            );
            collision_error["region_id"] = operation.region_id;
            return true;
        }
        region_load_count++;
        if(estimated_loaded_region_bytes() > max_estimated_region_bytes){
            const int32_t desired_index =
                desired_collision_regions.find(operation.region_id);
            if(desired_index >= 0){
                desired_collision_regions.remove_at(desired_index);
            }
            if(!region_needed(operation.region_id) &&
                grid->runtime_unload_region(operation.region_id)){
                region_unload_count++;
            }
            collision_error = fail(
                "collision_memory_budget_exceeded",
                "Collision region loading exceeded the configured memory ceiling"
            );
            collision_error["region_id"] = operation.region_id;
            return true;
        }
    }
    if(grid->runtime_set_region_collision(operation.region_id, operation.enable, operation.refresh)){
        collision_apply_count++;
        const int32_t active_index = active_collision_regions.find(operation.region_id);
        if(operation.enable && active_index < 0){
            active_collision_regions.push_back(operation.region_id);
            active_collision_regions.sort();
        } else if(!operation.enable && active_index >= 0){
            active_collision_regions.remove_at(active_index);
        }
        if(!operation.enable){
            schedule_region_eviction_if_unowned(operation.region_id);
        }
    } else if(operation.enable){
        const int32_t desired_index =
            desired_collision_regions.find(operation.region_id);
        if(desired_index >= 0){
            desired_collision_regions.remove_at(desired_index);
        }
        collision_error = fail(
            "collision_shape_failed",
            "A bounded heightfield collision shape could not be created"
        );
        collision_error["region_id"] = operation.region_id;
        schedule_region_eviction_if_unowned(operation.region_id);
    }
    return true;
}

String MRuntimeScheduler::phase_name(WorkPhase p_phase) const {
    switch(p_phase){
        case WORK_LOAD_REGIONS: return "load_regions";
        case WORK_PREFLIGHT: return "preflight";
        case WORK_WRITE_HEIGHTS: return "write_heights";
        case WORK_GENERATE_NORMALS: return "generate_normals";
        case WORK_APPLY: return "apply";
        case WORK_ROLLBACK_HEIGHTS: return "rollback_heights";
        case WORK_ROLLBACK_NORMALS: return "rollback_normals";
        case WORK_ROLLBACK_APPLY: return "rollback_apply";
    }
    return "unknown";
}

String MRuntimeScheduler::timing_phase_name(TimingPhase p_phase) const {
    switch(p_phase){
        case TIMING_REGION_LOAD: return "region_load";
        case TIMING_PREFLIGHT: return "preflight";
        case TIMING_WRITE_HEIGHTS: return "write_heights";
        case TIMING_GENERATE_NORMALS: return "generate_normals";
        case TIMING_TEXTURE_APPLY: return "texture_apply";
        case TIMING_COLLISION: return "collision";
        case TIMING_EVICTION: return "eviction";
        case TIMING_ROLLBACK_HEIGHTS: return "rollback_heights";
        case TIMING_ROLLBACK_NORMALS: return "rollback_normals";
        case TIMING_ROLLBACK_APPLY: return "rollback_apply";
        case TIMING_PHASE_COUNT: break;
    }
    return "unknown";
}

Dictionary MRuntimeScheduler::phase_timing_snapshot() const {
    Dictionary timings;
    for(int32_t index=0; index < TIMING_PHASE_COUNT; index++){
        Dictionary phase;
        phase["total_usec"] = phase_total_usec[index];
        phase["longest_usec"] = phase_longest_usec[index];
        phase["invocations"] = phase_invocation_count[index];
        timings[timing_phase_name((TimingPhase)index)] = phase;
    }
    return timings;
}

Dictionary MRuntimeScheduler::step(int32_t p_max_sample_ops, int32_t p_max_region_ops) {
    if(grid == nullptr || !grid->is_created()){
        return fail("grid_not_created", "Create the terrain grid before stepping runtime work");
    }
    if(p_max_sample_ops < MIN_STEP_SAMPLE_OPS || p_max_sample_ops > MAX_STEP_SAMPLE_OPS){
        return fail("invalid_sample_budget", "max_sample_ops must be between 128 and 16384");
    }
    if(p_max_region_ops < 1 || p_max_region_ops > MAX_STEP_REGION_OPS){
        return fail("invalid_region_budget", "max_region_ops must be between 1 and 16");
    }
    const auto started = std::chrono::steady_clock::now();
    step_count++;
    int32_t remaining_samples = p_max_sample_ops;
    int32_t remaining_regions = p_max_region_ops;
    Array completed_this_step;
    uint64_t phase_usec_before[TIMING_PHASE_COUNT] = {};
    for(int32_t index=0; index < TIMING_PHASE_COUNT; index++){
        phase_usec_before[index] = phase_total_usec[index];
    }

    while(remaining_regions > 0 && !pending_evictions.is_empty()){
        ScopedRuntimeTiming timing(
            phase_total_usec[TIMING_EVICTION],
            phase_longest_usec[TIMING_EVICTION],
            phase_invocation_count[TIMING_EVICTION]
        );
        process_one_eviction();
        remaining_regions--;
    }
    while(remaining_regions > 0 && !collision_operations.is_empty()){
        ScopedRuntimeTiming timing(
            phase_total_usec[TIMING_COLLISION],
            phase_longest_usec[TIMING_COLLISION],
            phase_invocation_count[TIMING_COLLISION]
        );
        process_one_collision_operation();
        remaining_regions--;
    }

    const int32_t work_index = choose_pending();
    if(work_index >= 0){
        TileWork& work = pending.write[work_index];
        if(work.cancelled){
            bool rollback_complete = work.write_cursor <= 0;
            if(!rollback_complete){
                if(work.phase != WORK_ROLLBACK_HEIGHTS &&
                    work.phase != WORK_ROLLBACK_NORMALS &&
                    work.phase != WORK_ROLLBACK_APPLY){
                    work.phase = WORK_ROLLBACK_HEIGHTS;
                    work.rollback_cursor = 0;
                }
                if(work.phase == WORK_ROLLBACK_HEIGHTS && remaining_samples > 0){
                    ScopedRuntimeTiming timing(
                        phase_total_usec[TIMING_ROLLBACK_HEIGHTS],
                        phase_longest_usec[TIMING_ROLLBACK_HEIGHTS],
                        phase_invocation_count[TIMING_ROLLBACK_HEIGHTS]
                    );
                    const int32_t stop = MIN(
                        work.write_cursor,
                        work.rollback_cursor+remaining_samples
                    );
                    for(int32_t index=work.rollback_cursor; index < stop; index++){
                        const int32_t local_y = index/work.width;
                        const int32_t local_x = index-local_y*work.width;
                        grid->set_height_by_pixel(
                            work.start_x+local_x,
                            work.start_y+local_y,
                            work.previous_heights[index]
                        );
                    }
                    remaining_samples -= stop-work.rollback_cursor;
                    work.rollback_cursor = stop;
                    if(work.rollback_cursor >= work.write_cursor){
                        work.phase = WORK_ROLLBACK_NORMALS;
                        work.normal_row = (int32_t)work.normal_top;
                    }
                }
                if(work.phase == WORK_ROLLBACK_NORMALS){
                    const int32_t normal_width =
                        (int32_t)(work.normal_right-work.normal_left+1);
                    if(remaining_samples >= normal_width){
                        ScopedRuntimeTiming timing(
                            phase_total_usec[TIMING_ROLLBACK_NORMALS],
                            phase_longest_usec[TIMING_ROLLBACK_NORMALS],
                            phase_invocation_count[TIMING_ROLLBACK_NORMALS]
                        );
                        const int32_t rows = remaining_samples/normal_width;
                        const int32_t last_row = MIN(
                            (int32_t)work.normal_bottom,
                            work.normal_row+rows-1
                        );
                        grid->update_normals(
                            work.normal_left,
                            work.normal_right,
                            (uint32_t)work.normal_row,
                            (uint32_t)last_row
                        );
                        remaining_samples -=
                            (last_row-work.normal_row+1)*normal_width;
                        work.normal_row = last_row+1;
                    }
                    rollback_complete =
                        work.normal_row > (int32_t)work.normal_bottom;
                    if(rollback_complete){
                        grid->runtime_mark_region_normals_dirty(work.region_ids);
                        work.phase = WORK_ROLLBACK_APPLY;
                        work.rollback_apply_region_cursor = 0;
                        rollback_complete = false;
                    }
                }
                if(work.phase == WORK_ROLLBACK_APPLY){
                    while(work.rollback_apply_region_cursor < work.region_ids.size() &&
                        remaining_regions > 0){
                        ScopedRuntimeTiming timing(
                            phase_total_usec[TIMING_ROLLBACK_APPLY],
                            phase_longest_usec[TIMING_ROLLBACK_APPLY],
                            phase_invocation_count[TIMING_ROLLBACK_APPLY]
                        );
                        Vector<int32_t> one_region;
                        one_region.push_back(
                            work.region_ids[work.rollback_apply_region_cursor]
                        );
                        const int32_t uploads =
                            grid->runtime_upload_region_ids(one_region);
                        work.rollback_texture_uploads += uploads;
                        texture_upload_count += uploads;
                        work.rollback_apply_region_cursor++;
                        remaining_regions--;
                    }
                    rollback_complete =
                        work.rollback_apply_region_cursor >= work.region_ids.size();
                }
            }
            if(rollback_complete){
                Dictionary result = work.superseded
                    ? fail("coalesced", "Runtime work was superseded by a newer revision")
                    : fail("cancelled", "Runtime work was cancelled before installation");
                result["work_key"] = work.key;
                result["revision"] = work.revision;
                result["status"] = work.superseded ? "coalesced" : "cancelled";
                result["rollback_texture_uploads"] = work.rollback_texture_uploads;
                completed_this_step.push_back(result);
                if(!work.superseded){
                    cancelled_count++;
                }
                finish_cancelled_work(work_index, result);
            }
        } else {
            while(work.phase == WORK_LOAD_REGIONS && remaining_regions > 0){
                if(work.region_cursor >= work.region_ids.size()){
                    work.phase = WORK_PREFLIGHT;
                    work.sample_cursor = 0;
                    break;
                }
                const int32_t region_id = work.region_ids[work.region_cursor++];
                if(!grid->runtime_region_is_loaded(region_id)){
                    ScopedRuntimeTiming timing(
                        phase_total_usec[TIMING_REGION_LOAD],
                        phase_longest_usec[TIMING_REGION_LOAD],
                        phase_invocation_count[TIMING_REGION_LOAD]
                    );
                    if(!grid->runtime_load_region(region_id)){
                        Dictionary result = fail("region_load_failed", "A required terrain region could not be loaded");
                        result["work_key"] = work.key;
                        result["revision"] = work.revision;
                        completed_this_step.push_back(result);
                        finish_work(work_index, result);
                        goto step_complete;
                    }
                    region_load_count++;
                    remaining_regions--;
                    if(estimated_loaded_region_bytes() > max_estimated_region_bytes){
                        schedule_region_eviction_if_unowned(region_id);
                        Dictionary result = fail("runtime_memory_budget_exceeded", "Loaded terrain regions exceed the configured memory ceiling");
                        result["work_key"] = work.key;
                        result["revision"] = work.revision;
                        completed_this_step.push_back(result);
                        finish_work(work_index, result);
                        goto step_complete;
                    }
                }
            }

            if(work.phase == WORK_PREFLIGHT && remaining_samples > 0){
                ScopedRuntimeTiming timing(
                    phase_total_usec[TIMING_PREFLIGHT],
                    phase_longest_usec[TIMING_PREFLIGHT],
                    phase_invocation_count[TIMING_PREFLIGHT]
                );
                const int32_t sample_count = work.heights.size();
                const int32_t stop = MIN(sample_count, work.sample_cursor+remaining_samples);
                for(int32_t index=work.sample_cursor; index < stop; index++){
                    const int32_t local_y = index/work.width;
                    const int32_t local_x = index-local_y*work.width;
                    const uint32_t x = (uint32_t)(work.start_x+local_x);
                    const uint32_t y = (uint32_t)(work.start_y+local_y);
                    if(!grid->can_set_height_by_pixel(x,y)){
                        Dictionary result = fail("tile_not_resident", "Every affected region and shared border must be resident before apply");
                        result["work_key"] = work.key;
                        result["revision"] = work.revision;
                        completed_this_step.push_back(result);
                        finish_work(work_index, result);
                        goto step_complete;
                    }
                    work.previous_heights.set(index, grid->get_height_by_pixel(x,y));
                }
                remaining_samples -= stop-work.sample_cursor;
                work.sample_cursor = stop;
                if(work.sample_cursor >= sample_count){
                    if(!grid->can_update_normals(
                        work.normal_left,
                        work.normal_right,
                        work.normal_top,
                        work.normal_bottom
                    )){
                        Dictionary result = fail("normal_halo_not_resident", "Every normal destination and height source in the expanded halo must be resident before apply");
                        result["work_key"] = work.key;
                        result["revision"] = work.revision;
                        completed_this_step.push_back(result);
                        finish_work(work_index, result);
                        goto step_complete;
                    }
                    work.phase = WORK_WRITE_HEIGHTS;
                }
            }

            if(work.phase == WORK_WRITE_HEIGHTS && remaining_samples > 0){
                ScopedRuntimeTiming timing(
                    phase_total_usec[TIMING_WRITE_HEIGHTS],
                    phase_longest_usec[TIMING_WRITE_HEIGHTS],
                    phase_invocation_count[TIMING_WRITE_HEIGHTS]
                );
                const int32_t sample_count = work.heights.size();
                const int32_t stop = MIN(sample_count, work.write_cursor+remaining_samples);
                for(int32_t index=work.write_cursor; index < stop; index++){
                    const int32_t local_y = index/work.width;
                    const int32_t local_x = index-local_y*work.width;
                    grid->set_height_by_pixel(
                        work.start_x+local_x,
                        work.start_y+local_y,
                        work.heights[index]
                    );
                }
                remaining_samples -= stop-work.write_cursor;
                work.write_cursor = stop;
                if(work.write_cursor >= sample_count){
                    work.phase = WORK_GENERATE_NORMALS;
                }
            }

            if(work.phase == WORK_GENERATE_NORMALS){
                const int32_t normal_width = (int32_t)(work.normal_right-work.normal_left+1);
                if(remaining_samples >= normal_width){
                    ScopedRuntimeTiming timing(
                        phase_total_usec[TIMING_GENERATE_NORMALS],
                        phase_longest_usec[TIMING_GENERATE_NORMALS],
                        phase_invocation_count[TIMING_GENERATE_NORMALS]
                    );
                    const int32_t rows = remaining_samples/normal_width;
                    const int32_t last_row = MIN(
                        (int32_t)work.normal_bottom,
                        work.normal_row+rows-1
                    );
                    grid->update_normals(
                        work.normal_left,
                        work.normal_right,
                        (uint32_t)work.normal_row,
                        (uint32_t)last_row
                    );
                    remaining_samples -=
                        (last_row-work.normal_row+1)*normal_width;
                    work.normal_row = last_row+1;
                }
                if(work.normal_row > (int32_t)work.normal_bottom){
                    grid->runtime_mark_region_normals_dirty(work.region_ids);
                    work.phase = WORK_APPLY;
                }
            }

            if(work.phase == WORK_APPLY && remaining_regions > 0){
                while(work.apply_region_cursor < work.region_ids.size() &&
                    remaining_regions > 0){
                    ScopedRuntimeTiming timing(
                        phase_total_usec[TIMING_TEXTURE_APPLY],
                        phase_longest_usec[TIMING_TEXTURE_APPLY],
                        phase_invocation_count[TIMING_TEXTURE_APPLY]
                    );
                    Vector<int32_t> one_region;
                    one_region.push_back(
                        work.region_ids[work.apply_region_cursor]
                    );
                    const int32_t uploads =
                        grid->runtime_upload_region_ids(one_region);
                    work.texture_uploads += uploads;
                    texture_upload_count += uploads;
                    work.apply_region_cursor++;
                    remaining_regions--;
                }
                if(work.apply_region_cursor >= work.region_ids.size()){
                    queue_collision_refresh(work.region_ids, work.update_collision);
                    install_resident(work);
                    Dictionary result;
                    result["ok"] = true;
                    result["api_version"] = 2;
                    result["code"] = "ok";
                    result["status"] = "completed";
                    result["work_key"] = work.key;
                    result["revision"] = work.revision;
                    result["written_samples"] = work.heights.size();
                    result["pixel_origin"] = Vector2i(work.start_x,work.start_y);
                    result["pixel_size"] = Vector2i(work.width,work.height);
                    result["normal_origin"] = Vector2i(work.normal_left,work.normal_top);
                    result["normal_size"] = Vector2i(
                        work.normal_right-work.normal_left+1,
                        work.normal_bottom-work.normal_top+1
                    );
                    result["affected_regions"] = work.region_ids.size();
                    result["texture_uploads"] = work.texture_uploads;
                    result["collision_disposition"] = work.update_collision
                        ? "queued_bounded_refresh"
                        : "refreshed_if_already_active";
                    completed_this_step.push_back(result);
                    completed_count++;
                    finish_work(work_index, result);
                }
            }
        }
    }

step_complete:
    const uint64_t elapsed_usec = (uint64_t)std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::steady_clock::now()-started
    ).count();
    longest_step_usec = MAX(longest_step_usec, elapsed_usec);
    Dictionary result;
    result["ok"] = true;
    result["code"] = "ok";
    result["status"] = pending.is_empty() && pending_evictions.is_empty() && collision_operations.is_empty()
        ? "idle"
        : "pending";
    result["sample_ops"] = p_max_sample_ops-remaining_samples;
    result["region_ops"] = p_max_region_ops-remaining_regions;
    result["elapsed_usec"] = elapsed_usec;
    Dictionary phase_usec;
    for(int32_t index=0; index < TIMING_PHASE_COUNT; index++){
        phase_usec[timing_phase_name((TimingPhase)index)] =
            phase_total_usec[index]-phase_usec_before[index];
    }
    result["phase_usec"] = phase_usec;
    result["completed"] = completed_this_step;
    result["pending_work"] = pending.size();
    result["pending_evictions"] = pending_evictions.size();
    result["pending_collision_ops"] = collision_operations.size();
    return result;
}

Dictionary MRuntimeScheduler::cancel(const String& p_work_key, int64_t p_revision) {
    const int32_t index = find_pending(p_work_key);
    if(index < 0){
        Dictionary result;
        result["ok"] = true;
        result["code"] = "ok";
        result["status"] = "not_pending";
        return result;
    }
    TileWork& work = pending.write[index];
    if(work.replacement != nullptr &&
        (p_revision < 0 || work.replacement->revision == p_revision)){
        const Vector<int32_t> replacement_regions =
            work.replacement->region_ids;
        Dictionary cancelled = fail(
            "cancelled",
            "A staged replacement was cancelled before mutation"
        );
        cancelled["work_key"] = work.replacement->key;
        cancelled["revision"] = work.replacement->revision;
        cancelled["status"] = "cancelled";
        push_result(cancelled);
        work.replacement.reset();
        for(int32_t region_id : replacement_regions){
            schedule_region_eviction_if_unowned(region_id);
        }
        cancelled_count++;
        if(p_revision >= 0){
            Dictionary result;
            result["ok"] = true;
            result["code"] = "ok";
            result["status"] = "replacement_cancelled";
            result["work_key"] = p_work_key;
            result["revision"] = p_revision;
            return result;
        }
    }
    if(p_revision >= 0 && work.revision != p_revision){
        return fail("revision_mismatch", "The pending work revision does not match the cancellation request");
    }
    work.cancelled = true;
    Dictionary result;
    result["ok"] = true;
    result["code"] = "ok";
    result["status"] = "cancellation_queued";
    result["work_key"] = p_work_key;
    result["revision"] = work.revision;
    return result;
}

Dictionary MRuntimeScheduler::release_tile(const String& p_work_key, int64_t p_revision) {
    bool matched = false;
    bool pending_release = false;
    bool resident_release = false;
    const int32_t pending_index = find_pending(p_work_key);
    if(pending_index >= 0){
        TileWork& work = pending.write[pending_index];
        if(p_revision < 0 || work.revision == p_revision){
            work.cancelled = true;
            matched = true;
            pending_release = true;
        }
        if(work.replacement != nullptr &&
            (p_revision < 0 || work.replacement->revision == p_revision)){
            const Vector<int32_t> replacement_regions =
                work.replacement->region_ids;
            Dictionary cancelled = fail(
                "cancelled",
                "A staged replacement was released before mutation"
            );
            cancelled["work_key"] = work.replacement->key;
            cancelled["revision"] = work.replacement->revision;
            cancelled["status"] = "cancelled";
            push_result(cancelled);
            work.replacement.reset();
            for(int32_t region_id : replacement_regions){
                schedule_region_eviction_if_unowned(region_id);
            }
            cancelled_count++;
            matched = true;
            pending_release = true;
        }
    }
    const int32_t resident_index = find_resident(p_work_key);
    if(resident_index >= 0 &&
        (p_revision < 0 || resident[resident_index].revision == p_revision)){
        schedule_resident_release(resident_index);
        matched = true;
        resident_release = true;
    }
    if(p_revision >= 0 && !matched){
        return fail("revision_mismatch", "The resident tile revision does not match the release request");
    }
    Dictionary result;
    result["ok"] = true;
    result["code"] = "ok";
    result["status"] = resident_release
        ? "release_queued"
        : (pending_release ? "pending_release" : "already_released");
    result["work_key"] = p_work_key;
    result["pending_evictions"] = pending_evictions.size();
    return result;
}

Dictionary MRuntimeScheduler::release_height_tile(
    int32_t p_start_x,
    int32_t p_start_y,
    int32_t p_width,
    int32_t p_height
) {
    for(int32_t index=0; index < resident.size(); index++){
        const ResidentTile& tile = resident[index];
        if(tile.start_x == p_start_x && tile.start_y == p_start_y &&
            tile.width == p_width && tile.height == p_height){
            return release_tile(tile.key, -1);
        }
    }
    for(int32_t index=0; index < pending.size(); index++){
        const TileWork& work = pending[index];
        if(work.start_x == p_start_x && work.start_y == p_start_y &&
            work.width == p_width && work.height == p_height){
            return release_tile(work.key, -1);
        }
        if(work.replacement != nullptr &&
            work.replacement->start_x == p_start_x &&
            work.replacement->start_y == p_start_y &&
            work.replacement->width == p_width &&
            work.replacement->height == p_height){
            return release_tile(work.key, -1);
        }
    }
    Dictionary result;
    result["ok"] = true;
    result["code"] = "ok";
    result["status"] = "already_released";
    return result;
}

Dictionary MRuntimeScheduler::request_collision_focus(
    int32_t p_focus_x,
    int32_t p_focus_y,
    int32_t p_radius_regions,
    int32_t p_max_regions,
    int64_t p_revision
) {
    if(grid == nullptr || !grid->is_created()){
        return fail("grid_not_created", "Create the terrain grid before requesting collision");
    }
    if(p_focus_x < 0 || p_focus_y < 0 || p_focus_x >= (int32_t)grid->pixel_width ||
        p_focus_y >= (int32_t)grid->pixel_height){
        return fail("collision_focus_out_of_bounds", "Collision focus must be inside the terrain pixel grid");
    }
    if(p_radius_regions < 0 || p_radius_regions > 4){
        return fail("invalid_collision_radius", "Collision radius must be between 0 and 4 regions");
    }
    if(p_max_regions < 0 || p_max_regions > max_collision_regions){
        return fail(
            "invalid_collision_request_limit",
            "Requested collision regions must be between zero and the configured ceiling"
        );
    }
    if(p_revision <= collision_revision){
        return fail("stale_collision_revision", "Collision focus revisions must increase monotonically");
    }
    const MGridPos grid_size = grid->get_region_grid_size();
    const int32_t center_x = MIN((int32_t)grid_size.x-1, p_focus_x/(int32_t)grid->rp);
    const int32_t center_y = MIN((int32_t)grid_size.z-1, p_focus_y/(int32_t)grid->rp);
    Vector<int32_t> desired;
    auto distance_for = [grid_size,center_x,center_y](int32_t p_id) {
        const int32_t x = p_id%(int32_t)grid_size.x;
        const int32_t y = p_id/(int32_t)grid_size.x;
        return std::abs(x-center_x)+std::abs(y-center_y);
    };
    if(p_max_regions > 0){
        for(int32_t y=center_y-p_radius_regions; y<=center_y+p_radius_regions; y++){
            for(int32_t x=center_x-p_radius_regions; x<=center_x+p_radius_regions; x++){
                if(x < 0 || y < 0 || x >= grid_size.x || y >= grid_size.z){
                    continue;
                }
                desired.push_back(x+y*(int32_t)grid_size.x);
            }
        }
    }
    for(int32_t left=0; left < desired.size(); left++){
        for(int32_t right=left+1; right < desired.size(); right++){
            const int32_t left_distance = distance_for(desired[left]);
            const int32_t right_distance = distance_for(desired[right]);
            if(right_distance < left_distance ||
                (right_distance == left_distance && desired[right] < desired[left])){
                const int32_t swap = desired[left];
                desired.write[left] = desired[right];
                desired.write[right] = swap;
            }
        }
    }
    while(desired.size() > p_max_regions){
        desired.remove_at(desired.size()-1);
    }

    const Vector<int32_t> previous_desired = desired_collision_regions;
    desired_collision_regions = desired;
    const bool exceeds_residency =
        runtime_owned_region_count_with(Vector<int32_t>()) > max_resident_regions;
    desired_collision_regions = previous_desired;
    if(exceeds_residency){
        return fail(
            "collision_residency_budget_exceeded",
            "Collision focus plus terrain work exceeds the configured resident-region ceiling"
        );
    }

    collision_revision = p_revision;
    collision_focus_explicit = true;
    desired_collision_regions = desired;
    collision_operations.clear();
    collision_error.clear();
    for(int32_t region_id : active_collision_regions){
        if(grid->runtime_region_has_collision(region_id) && desired.find(region_id) < 0){
            RegionOperation operation;
            operation.region_id = region_id;
            operation.revision = collision_revision;
            operation.enable = false;
            collision_operations.push_back(operation);
        }
    }
    for(int32_t region_id : desired){
        if(!grid->runtime_region_has_collision(region_id)){
            RegionOperation operation;
            operation.region_id = region_id;
            operation.revision = collision_revision;
            operation.enable = true;
            collision_operations.push_back(operation);
        }
    }
    Dictionary result;
    result["ok"] = true;
    result["code"] = "ok";
    result["status"] = collision_operations.is_empty() ? "ready" : "queued";
    result["revision"] = collision_revision;
    PackedInt32Array ids;
    for(int32_t region_id : desired){
        ids.push_back(region_id);
    }
    result["desired_regions"] = ids;
    result["pending_operations"] = collision_operations.size();
    return result;
}

Dictionary MRuntimeScheduler::snapshot() const {
    Dictionary result;
    result["kind"] = "mterrain-runtime-state/v2";
    result["api_version"] = 2;
    Dictionary limits;
    limits["max_pending_work"] = max_pending_work;
    limits["max_resident_tiles"] = max_resident_tiles;
    limits["max_resident_regions"] = max_resident_regions;
    limits["max_collision_regions"] = max_collision_regions;
    limits["max_estimated_region_bytes"] = max_estimated_region_bytes;
    result["limits"] = limits;

    Array pending_state;
    for(const TileWork& work : pending){
        Dictionary entry;
        entry["work_key"] = work.key;
        entry["revision"] = work.revision;
        entry["priority"] = work.priority;
        entry["phase"] = phase_name(work.phase);
        entry["cancelled"] = work.cancelled;
        entry["sample_cursor"] = work.sample_cursor;
        entry["write_cursor"] = work.write_cursor;
        entry["apply_region_cursor"] = work.apply_region_cursor;
        entry["rollback_cursor"] = work.rollback_cursor;
        entry["rollback_apply_region_cursor"] = work.rollback_apply_region_cursor;
        entry["sample_count"] = work.heights.size();
        entry["affected_regions"] = work.region_ids.size();
        if(work.replacement != nullptr){
            Dictionary replacement;
            replacement["revision"] = work.replacement->revision;
            replacement["priority"] = work.replacement->priority;
            replacement["sample_count"] = work.replacement->heights.size();
            replacement["affected_regions"] =
                work.replacement->region_ids.size();
            entry["replacement"] = replacement;
        }
        pending_state.push_back(entry);
    }
    result["pending"] = pending_state;

    Array resident_state;
    for(const ResidentTile& tile : resident){
        Dictionary entry;
        entry["work_key"] = tile.key;
        entry["revision"] = tile.revision;
        entry["pixel_origin"] = Vector2i(tile.start_x,tile.start_y);
        entry["pixel_size"] = Vector2i(tile.width,tile.height);
        entry["affected_regions"] = tile.region_ids.size();
        resident_state.push_back(entry);
    }
    result["resident"] = resident_state;
    result["resident_tile_count"] = resident.size();
    result["runtime_owned_region_count"] = runtime_owned_region_count_with(Vector<int32_t>());
    result["loaded_region_count"] = managed_loaded_region_count();
    result["estimated_loaded_region_bytes"] = estimated_loaded_region_bytes();
    result["pending_evictions"] = pending_evictions.size();
    result["visual_lod"] = grid != nullptr
        ? grid->runtime_lod_snapshot()
        : Dictionary();

    PackedInt32Array collision_regions;
    Array collision_region_state;
    bool collision_ready = collision_operations.is_empty() &&
        collision_error.is_empty();
    for(int32_t region_id : desired_collision_regions){
        collision_regions.push_back(region_id);
        const bool region_ready = grid != nullptr &&
            grid->runtime_region_has_collision(region_id);
        Dictionary region_entry;
        region_entry["region_id"] = region_id;
        region_entry["ready"] = region_ready;
        region_entry["generation"] = grid != nullptr
            ? grid->runtime_region_collision_generation(region_id)
            : 0;
        collision_region_state.push_back(region_entry);
        if(!region_ready){
            collision_ready = false;
        }
    }
    Dictionary collision;
    collision["revision"] = collision_revision;
    collision["ready"] = collision_ready;
    collision["desired_regions"] = collision_regions;
    PackedInt32Array active_regions;
    for(int32_t region_id : active_collision_regions){
        active_regions.push_back(region_id);
    }
    collision["active_regions"] = active_regions;
    collision["regions"] = collision_region_state;
    collision["pending_operations"] = collision_operations.size();
    collision["error"] = collision_error.duplicate(true);
    result["collision"] = collision;

    Dictionary metrics;
    metrics["queued"] = queued_count;
    metrics["completed"] = completed_count;
    metrics["cancelled"] = cancelled_count;
    metrics["coalesced"] = coalesced_count;
    metrics["evicted_tiles"] = evicted_tile_count;
    metrics["region_loads"] = region_load_count;
    metrics["region_unloads"] = region_unload_count;
    metrics["texture_uploads"] = texture_upload_count;
    metrics["collision_applies"] = collision_apply_count;
    metrics["steps"] = step_count;
    metrics["longest_step_usec"] = longest_step_usec;
    metrics["phase_timing_contract"] = "mterrain-runtime-phase-timings/v1";
    metrics["phase_timings"] = phase_timing_snapshot();
    result["metrics"] = metrics;
    return result;
}

Dictionary MRuntimeScheduler::take_result(const String& p_work_key, int64_t p_revision) {
    for(int32_t index=0; index < completed_results.size(); index++){
        const Dictionary result = completed_results[index];
        if((String)result.get("work_key", "") == p_work_key &&
            (int64_t)result.get("revision", -1) == p_revision){
            completed_results.remove_at(index);
            return result;
        }
    }
    return fail("result_not_found", "No completed result matches the requested work key and revision");
}

Dictionary MRuntimeScheduler::apply_height_tile_immediate(
    int32_t p_start_x,
    int32_t p_start_y,
    int32_t p_width,
    int32_t p_height,
    const PackedFloat32Array& p_heights_m,
    bool p_update_collision
) {
    if(!pending.is_empty()){
        return fail(
            "work_in_progress",
            "Immediate compatibility apply requires an otherwise idle tile queue"
        );
    }
    compatibility_revision++;
    const String key = String("immediate:")+itos(p_start_x)+":"+itos(p_start_y)+":"+
        itos(p_width)+":"+itos(p_height);
    Dictionary queued = queue_height_tile(
        key,
        compatibility_revision,
        1000,
        p_start_x,
        p_start_y,
        p_width,
        p_height,
        p_heights_m,
        p_update_collision
    );
    if(!(bool)queued.get("ok", false)){
        return queued;
    }
    for(int32_t iteration=0; iteration < 256; iteration++){
        Dictionary result = take_result(key, compatibility_revision);
        if((bool)result.get("ok", false) || (String)result.get("code", "") != "result_not_found"){
            return result;
        }
        Dictionary stepped = step(MAX_STEP_SAMPLE_OPS, MAX_STEP_REGION_OPS);
        if(!(bool)stepped.get("ok", false)){
            return stepped;
        }
    }
    return fail("immediate_step_limit", "The bounded immediate compatibility call did not complete");
}

void MRuntimeScheduler::reset() {
    if(grid != nullptr && grid->is_created()){
        for(int32_t region_id : active_collision_regions){
            if(grid->runtime_region_has_collision(region_id)){
                grid->runtime_set_region_collision(region_id, false);
            }
        }
    }
    pending.clear();
    resident.clear();
    pending_evictions.clear();
    collision_operations.clear();
    desired_collision_regions.clear();
    active_collision_regions.clear();
    completed_results.clear();
    sequence = 0;
    compatibility_revision = 0;
    collision_revision = -1;
    collision_focus_explicit = false;
    collision_error.clear();
    queued_count = 0;
    completed_count = 0;
    cancelled_count = 0;
    coalesced_count = 0;
    evicted_tile_count = 0;
    region_load_count = 0;
    region_unload_count = 0;
    texture_upload_count = 0;
    collision_apply_count = 0;
    step_count = 0;
    longest_step_usec = 0;
    for(int32_t index=0; index < TIMING_PHASE_COUNT; index++){
        phase_total_usec[index] = 0;
        phase_longest_usec[index] = 0;
        phase_invocation_count[index] = 0;
    }
}
