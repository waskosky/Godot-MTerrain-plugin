#include <mterrain/register.h>
#include <godot_cpp/godot.hpp>

extern "C" {
GDExtensionBool GDE_EXPORT test_library_init(GDExtensionInterfaceGetProcAddress get_proc,
        GDExtensionClassLibraryPtr library, GDExtensionInitialization *initialization) {
    godot::GDExtensionBinding::InitObject init(get_proc, library, initialization);
    init.register_initializer(initialize_mterrain);
    init.register_terminator(uninitialize_mterrain);
    init.set_minimum_library_initialization_level(godot::MODULE_INITIALIZATION_LEVEL_SCENE);
    return init.init();
}
}
