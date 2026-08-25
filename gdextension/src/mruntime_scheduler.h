#ifndef MTERRAIN_RUNTIME_SCHEDULER_H
#define MTERRAIN_RUNTIME_SCHEDULER_H

#include <cstdint>
#include <memory>

#include <godot_cpp/templates/vector.hpp>
#include <godot_cpp/variant/dictionary.hpp>
#include <godot_cpp/variant/packed_float32_array.hpp>
#include <godot_cpp/variant/packed_int32_array.hpp>
#include <godot_cpp/variant/string.hpp>

class MGrid;

using namespace godot;

class MRuntimeScheduler {
public:
    explicit MRuntimeScheduler(MGrid* p_grid);
    ~MRuntimeScheduler() = default;

    Dictionary configure_limits(const Dictionary& p_limits);
    Dictionary queue_height_tile(
        const String& p_work_key,
        int64_t p_revision,
        int32_t p_priority,
        int32_t p_start_x,
        int32_t p_start_y,
        int32_t p_width,
        int32_t p_height,
        const PackedFloat32Array& p_heights_m,
        bool p_update_collision
    );
    Dictionary step(int32_t p_max_sample_ops, int32_t p_max_region_ops);
    Dictionary cancel(const String& p_work_key, int64_t p_revision);
    Dictionary release_tile(const String& p_work_key, int64_t p_revision);
    Dictionary release_height_tile(
        int32_t p_start_x,
        int32_t p_start_y,
        int32_t p_width,
        int32_t p_height
    );
    Dictionary request_collision_focus(
        int32_t p_focus_x,
        int32_t p_focus_y,
        int32_t p_radius_regions,
        int32_t p_max_regions,
        int64_t p_revision
    );
    Dictionary snapshot() const;
    Dictionary take_result(const String& p_work_key, int64_t p_revision);
    Dictionary apply_height_tile_immediate(
        int32_t p_start_x,
        int32_t p_start_y,
        int32_t p_width,
        int32_t p_height,
        const PackedFloat32Array& p_heights_m,
        bool p_update_collision
    );
    void reset();

private:
    enum WorkPhase : int32_t {
        WORK_LOAD_REGIONS = 0,
        WORK_PREFLIGHT = 1,
        WORK_WRITE_HEIGHTS = 2,
        WORK_GENERATE_NORMALS = 3,
        WORK_APPLY = 4,
        WORK_ROLLBACK_HEIGHTS = 5,
        WORK_ROLLBACK_NORMALS = 6,
        WORK_ROLLBACK_APPLY = 7,
    };

    struct TileWork {
        String key;
        int64_t revision = 0;
        int32_t priority = 0;
        uint64_t sequence = 0;
        int32_t start_x = 0;
        int32_t start_y = 0;
        int32_t width = 0;
        int32_t height = 0;
        uint32_t normal_left = 0;
        uint32_t normal_right = 0;
        uint32_t normal_top = 0;
        uint32_t normal_bottom = 0;
        PackedFloat32Array heights;
        PackedFloat32Array previous_heights;
        Vector<int32_t> region_ids;
        int32_t region_cursor = 0;
        int32_t sample_cursor = 0;
        int32_t write_cursor = 0;
        int32_t normal_row = 0;
        int32_t rollback_cursor = 0;
        int32_t rollback_apply_region_cursor = 0;
        int32_t apply_region_cursor = 0;
        int32_t texture_uploads = 0;
        int32_t rollback_texture_uploads = 0;
        WorkPhase phase = WORK_LOAD_REGIONS;
        bool update_collision = false;
        bool cancelled = false;
        bool superseded = false;
        std::shared_ptr<TileWork> replacement;
    };

    struct ResidentTile {
        String key;
        int64_t revision = 0;
        uint64_t last_touch = 0;
        int32_t start_x = 0;
        int32_t start_y = 0;
        int32_t width = 0;
        int32_t height = 0;
        Vector<int32_t> region_ids;
    };

    struct RegionOperation {
        int32_t region_id = -1;
        int64_t revision = 0;
        bool enable = false;
        bool refresh = false;
    };

    MGrid* grid = nullptr;
    Vector<TileWork> pending;
    Vector<ResidentTile> resident;
    Vector<int32_t> pending_evictions;
    Vector<RegionOperation> collision_operations;
    Vector<int32_t> desired_collision_regions;
    Vector<int32_t> active_collision_regions;
    Vector<Dictionary> completed_results;

    int32_t max_pending_work = 32;
    int32_t max_resident_tiles = 16;
    int32_t max_resident_regions = 16;
    int32_t max_collision_regions = 4;
    int64_t max_estimated_region_bytes = 64LL * 1024LL * 1024LL;
    uint64_t sequence = 0;
    int64_t compatibility_revision = 0;
    int64_t collision_revision = -1;
    bool collision_focus_explicit = false;
    Dictionary collision_error;

    uint64_t queued_count = 0;
    uint64_t completed_count = 0;
    uint64_t cancelled_count = 0;
    uint64_t coalesced_count = 0;
    uint64_t evicted_tile_count = 0;
    uint64_t region_load_count = 0;
    uint64_t region_unload_count = 0;
    uint64_t texture_upload_count = 0;
    uint64_t collision_apply_count = 0;
    uint64_t step_count = 0;
    uint64_t longest_step_usec = 0;

    Dictionary fail(const String& p_code, const String& p_message) const;
    Dictionary validate_and_build_work(
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
    ) const;
    int32_t find_pending(const String& p_key) const;
    int32_t find_resident(const String& p_key) const;
    int32_t choose_pending() const;
    int32_t choose_oldest_resident(const String& p_excluded_key) const;
    int32_t runtime_owned_region_count_with(const Vector<int32_t>& p_candidate) const;
    int32_t nonresident_owned_region_count_with(
        const Vector<int32_t>& p_candidate,
        int32_t p_excluded_pending_index,
        int32_t p_excluded_replacement_index
    ) const;
    Vector<int32_t> managed_loaded_region_ids() const;
    int32_t managed_loaded_region_count() const;
    int64_t estimated_loaded_region_bytes() const;
    bool region_needed(int32_t p_region_id) const;
    bool collision_region_desired(int32_t p_region_id) const;
    void schedule_resident_release(int32_t p_resident_index);
    void schedule_region_eviction_if_unowned(int32_t p_region_id);
    void install_resident(const TileWork& p_work);
    void finish_work(int32_t p_pending_index, const Dictionary& p_result);
    void finish_cancelled_work(int32_t p_pending_index, const Dictionary& p_result);
    void push_result(const Dictionary& p_result);
    void queue_collision_refresh(
        const Vector<int32_t>& p_region_ids,
        bool p_admit_if_unfocused
    );
    bool process_one_eviction();
    bool process_one_collision_operation();
    String phase_name(WorkPhase p_phase) const;
};

#endif
