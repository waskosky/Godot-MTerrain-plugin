shader_type spatial;



uniform sampler2D mterrain_heightmap:filter_nearest;
uniform sampler2D mterrain_normals:filter_nearest;
uniform vec4 mterrain_low_color : source_color = vec4(0.16, 0.28, 0.16, 1.0);
uniform vec4 mterrain_high_color : source_color = vec4(0.48, 0.44, 0.30, 1.0);
uniform vec4 mterrain_steep_color : source_color = vec4(0.28, 0.27, 0.25, 1.0);
uniform float mterrain_height_scale = 128.0;
uniform float mterrain_readable_emission : hint_range(0.0, 1.0) = 0.35;
uniform bool mterrain_surface_textures_enabled = false;
uniform int mterrain_surface_layer_count : hint_range(0, 4, 1) = 0;
uniform float mterrain_texture_world_scale = 12.0;
uniform sampler2DArray runtime_surface_layers:filter_linear_mipmap_anisotropic,repeat_enable;
uniform sampler2D runtime_splatmap:filter_linear;

uniform vec3 region_world_position;
uniform float region_size;
uniform float region_a;
uniform float region_b;
uniform int min_lod;
varying vec3 world_pos;
varying vec2 region_uv;
varying vec3 terrain_normal;
varying float terrain_height;

void vertex(){
	world_pos = (NODE_POSITION_WORLD + VERTEX);
	region_uv = (world_pos.xz - region_world_position.xz)/region_size;
	region_uv = region_uv*region_a + region_b;
	VERTEX.y = texture(mterrain_heightmap, region_uv).r;
	world_pos.y = VERTEX.y;
	terrain_height = VERTEX.y;
	vec3 n = texture(mterrain_normals, region_uv).rgb;
	n.rb=n.rb*2.0 - 1.0;
	terrain_normal = normalize(n);
	NORMAL = terrain_normal;

}

void fragment(){
	float height_mix = clamp(0.5 + terrain_height / max(mterrain_height_scale, 0.001) * 0.5, 0.0, 1.0);
	float steepness = 1.0 - clamp(terrain_normal.y, 0.0, 1.0);
	vec3 semantic_color = mix(mterrain_low_color.rgb, mterrain_high_color.rgb, height_mix);
	semantic_color = mix(semantic_color, mterrain_steep_color.rgb, smoothstep(0.30, 0.78, steepness));
	vec3 surface_color = semantic_color;
	if(mterrain_surface_textures_enabled && mterrain_surface_layer_count > 0){
		vec4 weights = max(texture(runtime_splatmap, region_uv), vec4(0.0));
		if(mterrain_surface_layer_count < 4){
			weights.w = 0.0;
		}
		if(mterrain_surface_layer_count < 3){
			weights.z = 0.0;
		}
		if(mterrain_surface_layer_count < 2){
			weights.y = 0.0;
		}
		float weight_total = dot(weights, vec4(1.0));
		if(weight_total > 0.0001){
			weights /= weight_total;
			vec2 surface_uv = world_pos.xz / max(mterrain_texture_world_scale, 0.001);
			vec3 sampled = texture(runtime_surface_layers, vec3(surface_uv, 0.0)).rgb * weights.x;
			if(mterrain_surface_layer_count > 1){
				sampled += texture(runtime_surface_layers, vec3(surface_uv, 1.0)).rgb * weights.y;
			}
			if(mterrain_surface_layer_count > 2){
				sampled += texture(runtime_surface_layers, vec3(surface_uv, 2.0)).rgb * weights.z;
			}
			if(mterrain_surface_layer_count > 3){
				sampled += texture(runtime_surface_layers, vec3(surface_uv, 3.0)).rgb * weights.w;
			}
			surface_color *= sampled;
		}
	}
	ALBEDO = surface_color;
	EMISSION = surface_color * mterrain_readable_emission;
	ROUGHNESS = 0.9;
}
