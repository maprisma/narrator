#include "my_application.h"

#include <flutter_linux/flutter_linux.h>
#ifdef GDK_WINDOWING_X11
#include <gdk/gdkx.h>
#endif

#include "flutter/generated_plugin_registrant.h"

struct _MyApplication {
  GtkApplication parent_instance;
  char** dart_entrypoint_arguments;
  FlMethodChannel* theme_channel;
  GDBusProxy* portal;
  GtkCssProvider* header_css;
  FlView* view;
};

G_DEFINE_TYPE(MyApplication, my_application, GTK_TYPE_APPLICATION)

// --- Desktop theme ----------------------------------------------------------
// The accent color comes from the XDG desktop portal (org.freedesktop.appearance accent-color),
// which COSMIC, GNOME and KDE fill in. Flutter itself already follows the portal's color-scheme;
// it sends back the colors of its page so the GTK header bar matches instead of staying the
// light Adwaita default.

// Unwraps the nested variants that Settings.Read (older portals) adds around the value.
static GVariant* unwrap_variant(GVariant* value) {
  GVariant* current = g_variant_ref(value);
  while (g_variant_is_of_type(current, G_VARIANT_TYPE_VARIANT)) {
    GVariant* inner = g_variant_get_variant(current);
    g_variant_unref(current);
    current = inner;
  }
  return current;
}

// Returns [r, g, b] for Dart, or null when the portal has no (valid) accent.
static FlValue* accent_to_fl(GVariant* value) {
  if (value == nullptr) return fl_value_new_null();
  g_autoptr(GVariant) color = unwrap_variant(value);
  if (!g_variant_is_of_type(color, G_VARIANT_TYPE("(ddd)"))) return fl_value_new_null();
  double r, g, b;
  g_variant_get(color, "(ddd)", &r, &g, &b);
  FlValue* list = fl_value_new_list();
  fl_value_append_take(list, fl_value_new_float(r));
  fl_value_append_take(list, fl_value_new_float(g));
  fl_value_append_take(list, fl_value_new_float(b));
  return list;
}

static GVariant* read_accent(MyApplication* self) {
  if (self->portal == nullptr) return nullptr;
  const char* methods[] = {"ReadOne", "Read"};
  for (const char* method : methods) {
    g_autoptr(GError) error = nullptr;
    g_autoptr(GVariant) result = g_dbus_proxy_call_sync(
        self->portal, method,
        g_variant_new("(ss)", "org.freedesktop.appearance", "accent-color"),
        G_DBUS_CALL_FLAGS_NONE, 1000, nullptr, &error);
    if (result != nullptr) {
      GVariant* value = nullptr;
      g_variant_get(result, "(v)", &value);
      return value;
    }
  }
  return nullptr;
}

static void portal_signal_cb(GDBusProxy* proxy, const gchar* sender,
                             const gchar* signal, GVariant* parameters,
                             gpointer user_data) {
  MyApplication* self = MY_APPLICATION(user_data);
  if (g_strcmp0(signal, "SettingChanged") != 0) return;
  const gchar* ns = nullptr;
  const gchar* key = nullptr;
  g_autoptr(GVariant) value = nullptr;
  g_variant_get(parameters, "(&s&sv)", &ns, &key, &value);
  if (g_strcmp0(ns, "org.freedesktop.appearance") != 0 ||
      g_strcmp0(key, "accent-color") != 0 || self->theme_channel == nullptr)
    return;
  g_autoptr(FlValue) accent = accent_to_fl(value);
  fl_method_channel_invoke_method(self->theme_channel, "accentChanged", accent,
                                  nullptr, nullptr, nullptr);
}

static const gchar* map_string(FlValue* args, const char* key,
                               const char* fallback) {
  FlValue* value = fl_value_lookup_string(args, key);
  if (value == nullptr || fl_value_get_type(value) != FL_VALUE_TYPE_STRING)
    return fallback;
  return fl_value_get_string(value);
}

static void set_header_colors(MyApplication* self, FlValue* args) {
  if (fl_value_get_type(args) != FL_VALUE_TYPE_MAP) return;
  const gchar* bg = map_string(args, "background", "#ffffff");
  const gchar* fg = map_string(args, "foreground", "#000000");
  const gchar* border = map_string(args, "border", "#cccccc");
  const gchar* surface = map_string(args, "surface", bg);
  FlValue* dark = fl_value_lookup_string(args, "dark");
  gboolean is_dark = dark != nullptr &&
                     fl_value_get_type(dark) == FL_VALUE_TYPE_BOOL &&
                     fl_value_get_bool(dark);

  // Dark Adwaita for the window buttons' icons, then our colors on top.
  g_object_set(gtk_settings_get_default(), "gtk-application-prefer-dark-theme",
               is_dark, nullptr);
  g_autofree gchar* css = g_strdup_printf(
      "headerbar, headerbar:backdrop {"
      "  background: %s; background-image: none; color: %s;"
      "  border-bottom: 1px solid %s; box-shadow: none; }"
      "headerbar .title, headerbar label { color: %s; }"
      "headerbar:backdrop .title, headerbar:backdrop label,"
      "headerbar:backdrop button { color: alpha(%s, 0.6); }"
      "headerbar button { color: %s; background: transparent;"
      "  background-image: none; border-color: transparent; box-shadow: none; }"
      "headerbar button:hover { background: alpha(%s, 0.12); }"
      "headerbar button:active { background: alpha(%s, 0.2); }"
      "window, decoration { background: %s; }",
      bg, fg, border, fg, fg, fg, fg, fg, surface);
  gtk_css_provider_load_from_data(self->header_css, css, -1, nullptr);

  if (self->view != nullptr) {
    GdkRGBA color;
    if (gdk_rgba_parse(&color, surface))
      fl_view_set_background_color(self->view, &color);
  }
}

static void theme_method_cb(FlMethodChannel* channel, FlMethodCall* call,
                            gpointer user_data) {
  MyApplication* self = MY_APPLICATION(user_data);
  const gchar* name = fl_method_call_get_name(call);
  g_autoptr(FlMethodResponse) response = nullptr;
  if (g_strcmp0(name, "getAccent") == 0) {
    g_autoptr(GVariant) value = read_accent(self);
    g_autoptr(FlValue) accent = accent_to_fl(value);
    response = FL_METHOD_RESPONSE(fl_method_success_response_new(accent));
  } else if (g_strcmp0(name, "setHeaderColors") == 0) {
    set_header_colors(self, fl_method_call_get_args(call));
    response = FL_METHOD_RESPONSE(fl_method_success_response_new(nullptr));
  } else {
    response = FL_METHOD_RESPONSE(fl_method_not_implemented_response_new());
  }
  fl_method_call_respond(call, response, nullptr);
}

static void setup_theme(MyApplication* self, FlView* view) {
  self->view = view;
  self->header_css = gtk_css_provider_new();
  gtk_style_context_add_provider_for_screen(
      gdk_screen_get_default(), GTK_STYLE_PROVIDER(self->header_css),
      GTK_STYLE_PROVIDER_PRIORITY_APPLICATION);

  g_autoptr(GError) error = nullptr;
  self->portal = g_dbus_proxy_new_for_bus_sync(
      G_BUS_TYPE_SESSION, G_DBUS_PROXY_FLAGS_DO_NOT_LOAD_PROPERTIES, nullptr,
      "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
      "org.freedesktop.portal.Settings", nullptr, &error);
  if (self->portal != nullptr)
    g_signal_connect(self->portal, "g-signal", G_CALLBACK(portal_signal_cb),
                     self);

  FlEngine* engine = fl_view_get_engine(view);
  g_autoptr(FlStandardMethodCodec) codec = fl_standard_method_codec_new();
  self->theme_channel = fl_method_channel_new(
      fl_engine_get_binary_messenger(engine), "maprisma_narrator/theme",
      FL_METHOD_CODEC(codec));
  fl_method_channel_set_method_call_handler(self->theme_channel,
                                            theme_method_cb, self, nullptr);
}

// Called when first Flutter frame received.
static void first_frame_cb(MyApplication* self, FlView* view) {
  gtk_widget_show(gtk_widget_get_toplevel(GTK_WIDGET(view)));
}

// Implements GApplication::activate.
static void my_application_activate(GApplication* application) {
  MyApplication* self = MY_APPLICATION(application);
  GtkWindow* window =
      GTK_WINDOW(gtk_application_window_new(GTK_APPLICATION(application)));

  // Use a header bar when running in GNOME as this is the common style used
  // by applications and is the setup most users will be using (e.g. Ubuntu
  // desktop).
  // If running on X and not using GNOME then just use a traditional title bar
  // in case the window manager does more exotic layout, e.g. tiling.
  // If running on Wayland assume the header bar will work (may need changing
  // if future cases occur).
  gboolean use_header_bar = TRUE;
#ifdef GDK_WINDOWING_X11
  GdkScreen* screen = gtk_window_get_screen(window);
  if (GDK_IS_X11_SCREEN(screen)) {
    const gchar* wm_name = gdk_x11_screen_get_window_manager_name(screen);
    if (g_strcmp0(wm_name, "GNOME Shell") != 0) {
      use_header_bar = FALSE;
    }
  }
#endif
  if (use_header_bar) {
    GtkHeaderBar* header_bar = GTK_HEADER_BAR(gtk_header_bar_new());
    gtk_widget_show(GTK_WIDGET(header_bar));
    gtk_header_bar_set_title(header_bar, "Maprisma Narrator");
    gtk_header_bar_set_show_close_button(header_bar, TRUE);
    gtk_window_set_titlebar(window, GTK_WIDGET(header_bar));
  } else {
    gtk_window_set_title(window, "Maprisma Narrator");
  }

  gtk_window_set_default_size(window, 640, 820);

  g_autoptr(FlDartProject) project = fl_dart_project_new();
  fl_dart_project_set_dart_entrypoint_arguments(
      project, self->dart_entrypoint_arguments);

  FlView* view = fl_view_new(project);
  GdkRGBA background_color;
  // Background defaults to black, override it here if necessary, e.g. #00000000
  // for transparent.
  gdk_rgba_parse(&background_color, "#000000");
  fl_view_set_background_color(view, &background_color);
  gtk_widget_show(GTK_WIDGET(view));
  gtk_container_add(GTK_CONTAINER(window), GTK_WIDGET(view));

  // Show the window when Flutter renders.
  // Requires the view to be realized so we can start rendering.
  g_signal_connect_swapped(view, "first-frame", G_CALLBACK(first_frame_cb),
                           self);
  gtk_widget_realize(GTK_WIDGET(view));

  fl_register_plugins(FL_PLUGIN_REGISTRY(view));
  setup_theme(self, view);

  gtk_widget_grab_focus(GTK_WIDGET(view));
}

// Implements GApplication::local_command_line.
static gboolean my_application_local_command_line(GApplication* application,
                                                  gchar*** arguments,
                                                  int* exit_status) {
  MyApplication* self = MY_APPLICATION(application);
  // Strip out the first argument as it is the binary name.
  self->dart_entrypoint_arguments = g_strdupv(*arguments + 1);

  g_autoptr(GError) error = nullptr;
  if (!g_application_register(application, nullptr, &error)) {
    g_warning("Failed to register: %s", error->message);
    *exit_status = 1;
    return TRUE;
  }

  g_application_activate(application);
  *exit_status = 0;

  return TRUE;
}

// Implements GApplication::startup.
static void my_application_startup(GApplication* application) {
  // MyApplication* self = MY_APPLICATION(object);

  // Perform any actions required at application startup.

  G_APPLICATION_CLASS(my_application_parent_class)->startup(application);
}

// Implements GApplication::shutdown.
static void my_application_shutdown(GApplication* application) {
  // MyApplication* self = MY_APPLICATION(object);

  // Perform any actions required at application shutdown.

  G_APPLICATION_CLASS(my_application_parent_class)->shutdown(application);
}

// Implements GObject::dispose.
static void my_application_dispose(GObject* object) {
  MyApplication* self = MY_APPLICATION(object);
  g_clear_pointer(&self->dart_entrypoint_arguments, g_strfreev);
  if (self->portal != nullptr)
    g_signal_handlers_disconnect_by_data(self->portal, self);
  g_clear_object(&self->portal);
  g_clear_object(&self->theme_channel);
  g_clear_object(&self->header_css);
  self->view = nullptr;
  G_OBJECT_CLASS(my_application_parent_class)->dispose(object);
}

static void my_application_class_init(MyApplicationClass* klass) {
  G_APPLICATION_CLASS(klass)->activate = my_application_activate;
  G_APPLICATION_CLASS(klass)->local_command_line =
      my_application_local_command_line;
  G_APPLICATION_CLASS(klass)->startup = my_application_startup;
  G_APPLICATION_CLASS(klass)->shutdown = my_application_shutdown;
  G_OBJECT_CLASS(klass)->dispose = my_application_dispose;
}

static void my_application_init(MyApplication* self) {}

MyApplication* my_application_new() {
  // Set the program name to the application ID, which helps various systems
  // like GTK and desktop environments map this running application to its
  // corresponding .desktop file. This ensures better integration by allowing
  // the application to be recognized beyond its binary name.
  g_set_prgname(APPLICATION_ID);

  return MY_APPLICATION(g_object_new(my_application_get_type(),
                                     "application-id", APPLICATION_ID, "flags",
                                     G_APPLICATION_NON_UNIQUE, nullptr));
}
