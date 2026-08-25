#include "mterrain.h"

#include <cmath>

#include <godot_cpp/classes/texture2d.hpp>
#include <godot_cpp/classes/texture2d_array.hpp>
#include <godot_cpp/variant/color.hpp>

#include "mruntime_scheduler.h"

namespace {
Dictionary runtime_api_unavailable() {
    Dictionary result;
    result["ok"] = false;
    result["api_version"] = 2;
    result["code"] = "runtime_scheduler_unavailable";
    result["message"] = "The runtime scheduler is unavailable";
    return result;
}

bool finite_color(const Color& p_color) {
    return std::isfinite(p_color.r) && std::isfinite(p_color.g) &&
        std::isfinite(p_color.b) && std::isfinite(p_color.a);
}

bool numeric_variant(const Variant& p_value) {
    return p_value.get_type() == Variant::INT ||
        p_value.get_type() == Variant::FLOAT;
}
}

Dictionary MTerrain::configure_runtime_limits(const Dictionary& limits) {
    return runtime_scheduler != nullptr
        ? runtime_scheduler->configure_limits(limits)
        : runtime_api_unavailable();
}

Dictionary MTerrain::queue_height_tile(
    const String& work_key,
    int64_t revision,
    int32_t priority,
    int32_t start_x,
    int32_t start_y,
    int32_t width,
    int32_t height,
    const PackedFloat32Array& heights_m,
    bool update_collision
) {
    return runtime_scheduler != nullptr
        ? runtime_scheduler->queue_height_tile(
            work_key,
            revision,
            priority,
            start_x,
            start_y,
            width,
            height,
            heights_m,
            update_collision
        )
        : runtime_api_unavailable();
}

Dictionary MTerrain::step_runtime_work(int32_t max_sample_ops, int32_t max_region_ops) {
    return runtime_scheduler != nullptr
        ? runtime_scheduler->step(max_sample_ops, max_region_ops)
        : runtime_api_unavailable();
}

Dictionary MTerrain::cancel_runtime_work(const String& work_key, int64_t revision) {
    return runtime_scheduler != nullptr
        ? runtime_scheduler->cancel(work_key, revision)
        : runtime_api_unavailable();
}

Dictionary MTerrain::release_runtime_tile(const String& work_key, int64_t revision) {
    return runtime_scheduler != nullptr
        ? runtime_scheduler->release_tile(work_key, revision)
        : runtime_api_unavailable();
}

Dictionary MTerrain::release_height_tile(
    int32_t start_x,
    int32_t start_y,
    int32_t width,
    int32_t height
) {
    return runtime_scheduler != nullptr
        ? runtime_scheduler->release_height_tile(start_x, start_y, width, height)
        : runtime_api_unavailable();
}

Dictionary MTerrain::request_runtime_collision_focus(
    int32_t focus_x,
    int32_t focus_y,
    int32_t radius_regions,
    int32_t max_regions,
    int64_t revision
) {
    return runtime_scheduler != nullptr
        ? runtime_scheduler->request_collision_focus(
            focus_x,
            focus_y,
            radius_regions,
            max_regions,
            revision
        )
        : runtime_api_unavailable();
}

Dictionary MTerrain::get_runtime_state() const {
    return runtime_scheduler != nullptr
        ? runtime_scheduler->snapshot()
        : runtime_api_unavailable();
}

Dictionary MTerrain::take_runtime_work_result(const String& work_key, int64_t revision) {
    return runtime_scheduler != nullptr
        ? runtime_scheduler->take_result(work_key, revision)
        : runtime_api_unavailable();
}

Dictionary MTerrain::configure_runtime_material(const Dictionary& configuration) {
    Dictionary result;
    result["ok"] = false;
    result["api_version"] = get_runtime_bridge_api_version();
    auto fail = [&result](const String& p_code, const String& p_message) {
        result["code"] = p_code;
        result["message"] = p_message;
        return result;
    };

    PackedStringArray accepted_keys;
    accepted_keys.push_back("low_color");
    accepted_keys.push_back("high_color");
    accepted_keys.push_back("steep_color");
    accepted_keys.push_back("height_scale");
    accepted_keys.push_back("texture_world_scale");
    accepted_keys.push_back("readable_emission");
    accepted_keys.push_back("surface_layer_count");
    accepted_keys.push_back("surface_layers");
    accepted_keys.push_back("splatmap");
    const Array supplied_keys = configuration.keys();
    for(int32_t index=0; index < supplied_keys.size(); index++){
        const Variant supplied_key = supplied_keys[index];
        if(supplied_key.get_type() != Variant::STRING &&
            supplied_key.get_type() != Variant::STRING_NAME){
            return fail("invalid_material_key", "Runtime material keys must be strings");
        }
        const String key = supplied_key;
        if(!accepted_keys.has(key)){
            return fail("unknown_material_key", "Unknown runtime material key: "+key);
        }
    }

    const Variant low_value = configuration.get(
        "low_color",
        Color(0.16f,0.28f,0.16f,1.0f)
    );
    const Variant high_value = configuration.get(
        "high_color",
        Color(0.48f,0.44f,0.30f,1.0f)
    );
    const Variant steep_value = configuration.get(
        "steep_color",
        Color(0.28f,0.27f,0.25f,1.0f)
    );
    const Variant height_scale_value = configuration.get("height_scale", 128.0f);
    const Variant texture_scale_value = configuration.get("texture_world_scale", 12.0f);
    const Variant emission_value = configuration.get("readable_emission", 0.35f);
    const Variant layer_count_value = configuration.get("surface_layer_count", 0);
    if(low_value.get_type() != Variant::COLOR ||
        high_value.get_type() != Variant::COLOR ||
        steep_value.get_type() != Variant::COLOR){
        return fail("invalid_material_color_type", "Runtime material colors must use Color values");
    }
    if(!numeric_variant(height_scale_value) ||
        !numeric_variant(texture_scale_value) ||
        !numeric_variant(emission_value)){
        return fail("invalid_material_number_type", "Runtime material scales and emission must be numeric");
    }
    if(layer_count_value.get_type() != Variant::INT){
        return fail("invalid_surface_layer_count_type", "surface_layer_count must be an integer");
    }

    const Color low_color = low_value;
    const Color high_color = high_value;
    const Color steep_color = steep_value;
    const float height_scale = height_scale_value;
    const float texture_world_scale = texture_scale_value;
    const float readable_emission = emission_value;
    const int32_t surface_layer_count = layer_count_value;
    if(!finite_color(low_color) || !finite_color(high_color) || !finite_color(steep_color)){
        return fail("non_finite_material_color", "Runtime material colors must be finite");
    }
    if(!std::isfinite(height_scale) || height_scale <= 0.0f || height_scale > 100000.0f){
        return fail("invalid_material_height_scale", "height_scale must be finite and between 0 and 100000");
    }
    if(!std::isfinite(texture_world_scale) || texture_world_scale < 0.25f || texture_world_scale > 4096.0f){
        return fail("invalid_material_texture_scale", "texture_world_scale must be between 0.25 and 4096");
    }
    if(!std::isfinite(readable_emission) || readable_emission < 0.0f || readable_emission > 1.0f){
        return fail("invalid_material_emission", "readable_emission must be between 0 and 1");
    }
    if(surface_layer_count < 0 || surface_layer_count > 4){
        return fail("surface_sample_limit", "Compatibility material blending is limited to four sampled layers");
    }

    const Variant surface_layers_value = configuration.get("surface_layers", Variant());
    const Variant splatmap_value = configuration.get("splatmap", Variant());
    if((surface_layers_value.get_type() != Variant::NIL &&
        surface_layers_value.get_type() != Variant::OBJECT) ||
        (splatmap_value.get_type() != Variant::NIL &&
        splatmap_value.get_type() != Variant::OBJECT)){
        return fail("invalid_surface_texture_type", "Runtime surface textures must be Resource objects");
    }
    Ref<Texture2DArray> surface_layers = surface_layers_value;
    Ref<Texture2D> splatmap = splatmap_value;
    if(surface_layer_count > 0){
        if(!surface_layers.is_valid() || !splatmap.is_valid()){
            return fail("surface_textures_missing", "Texture blending requires both surface_layers and splatmap");
        }
        if(surface_layers->get_layers() > 16 || surface_layers->get_layers() < surface_layer_count){
            return fail("surface_layer_limit", "Texture arrays are limited to 16 layers and must contain every sampled layer");
        }
        if(surface_layers->get_width() <= 0 || surface_layers->get_height() <= 0 ||
            surface_layers->get_width() > 2048 || surface_layers->get_height() > 2048 ||
            splatmap->get_width() <= 0 || splatmap->get_height() <= 0 ||
            splatmap->get_width() > 2048 || splatmap->get_height() > 2048){
            return fail("surface_texture_dimensions", "Runtime material textures must be between 1 and 2048 pixels per side");
        }
    }

    Ref<MTerrainMaterial> material = get_terrain_material();
    if(!material.is_valid() && grid != nullptr && grid->is_created()){
        material = grid->get_terrain_material();
    }
    if(!material.is_valid()){
        return fail("terrain_material_missing", "Configure or create the terrain material before applying runtime material policy");
    }
    Ref<Shader> shader = material->get_currect_shader();
    if(!shader.is_valid()){
        return fail("terrain_shader_missing", "The active terrain shader is unavailable");
    }
    PackedStringArray available_uniforms;
    const Array shader_uniforms = shader->get_shader_uniform_list();
    for(int32_t index=0; index < shader_uniforms.size(); index++){
        const Dictionary uniform = shader_uniforms[index];
        available_uniforms.push_back((String)uniform.get("name", ""));
    }
    PackedStringArray required_uniforms;
    required_uniforms.push_back("mterrain_low_color");
    required_uniforms.push_back("mterrain_high_color");
    required_uniforms.push_back("mterrain_steep_color");
    required_uniforms.push_back("mterrain_height_scale");
    required_uniforms.push_back("mterrain_texture_world_scale");
    required_uniforms.push_back("mterrain_readable_emission");
    required_uniforms.push_back("mterrain_surface_layer_count");
    required_uniforms.push_back("mterrain_surface_textures_enabled");
    required_uniforms.push_back("runtime_surface_layers");
    required_uniforms.push_back("runtime_splatmap");
    for(const String& required_uniform : required_uniforms){
        if(!available_uniforms.has(required_uniform)){
            return fail(
                "runtime_material_shader_contract",
                "The active terrain shader omits required uniform: "+required_uniform
            );
        }
    }
    material->set_default_uniform("mterrain_low_color", low_color);
    material->set_default_uniform("mterrain_high_color", high_color);
    material->set_default_uniform("mterrain_steep_color", steep_color);
    material->set_default_uniform("mterrain_height_scale", height_scale);
    material->set_default_uniform("mterrain_texture_world_scale", texture_world_scale);
    material->set_default_uniform("mterrain_readable_emission", readable_emission);
    material->set_default_uniform("mterrain_surface_layer_count", surface_layer_count);
    material->set_default_uniform("mterrain_surface_textures_enabled", surface_layer_count > 0);
    if(surface_layer_count > 0){
        material->set_default_uniform("runtime_surface_layers", surface_layers);
        material->set_default_uniform("runtime_splatmap", splatmap);
    } else {
        material->set_default_uniform("runtime_surface_layers", Variant());
        material->set_default_uniform("runtime_splatmap", Variant());
    }
    if(grid != nullptr && grid->is_created()){
        grid->refresh_all_regions_uniforms();
    }
    result["ok"] = true;
    result["code"] = "ok";
    result["surface_layer_count"] = surface_layer_count;
    result["max_surface_layers"] = 16;
    result["max_fragment_samples"] = 4;
    result["missing_texture_readable"] = true;
    return result;
}
