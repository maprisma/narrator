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
  FlMethodChannel* window_channel;
  GtkWindow* window;
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

// --- The window (window.dart) ------------------------------------------------
// Dart closes the window on Esc (as the close button: delete-event, so the app's exit handling
// runs), sizes it before it is shown (the saved size, fitted to the screen's work area) and hears
// every resize, which it saves unless the window is maximised, fullscreen or tiled.

static double number_arg(FlValue* args, const char* key) {
  if (args == nullptr || fl_value_get_type(args) != FL_VALUE_TYPE_MAP) return 0;
  FlValue* value = fl_value_lookup_string(args, key);
  if (value == nullptr) return 0;
  if (fl_value_get_type(value) == FL_VALUE_TYPE_INT) return fl_value_get_int(value);
  if (fl_value_get_type(value) == FL_VALUE_TYPE_FLOAT) return fl_value_get_float(value);
  return 0;
}

static FlValue* size_value(int width, int height) {
  FlValue* map = fl_value_new_map();
  fl_value_set_string_take(map, "width", fl_value_new_int(width));
  fl_value_set_string_take(map, "height", fl_value_new_int(height));
  return map;
}

static void window_method_cb(FlMethodChannel* channel, FlMethodCall* call,
                             gpointer user_data) {
  MyApplication* self = MY_APPLICATION(user_data);
  const gchar* name = fl_method_call_get_name(call);
  g_autoptr(FlMethodResponse) response = nullptr;
  if (self->window == nullptr) {
    response = FL_METHOD_RESPONSE(fl_method_error_response_new("no-window", "No window", nullptr));
  } else if (g_strcmp0(name, "close") == 0) {
    gtk_window_close(self->window);
    response = FL_METHOD_RESPONSE(fl_method_success_response_new(nullptr));
  } else if (g_strcmp0(name, "screen") == 0) {
    GdkDisplay* display = gtk_widget_get_display(GTK_WIDGET(self->window));
    GdkWindow* gdk_window = gtk_widget_get_window(GTK_WIDGET(self->window));
    GdkMonitor* monitor = gdk_window != nullptr
                              ? gdk_display_get_monitor_at_window(display, gdk_window)
                              : nullptr;
    if (monitor == nullptr) monitor = gdk_display_get_primary_monitor(display);
    if (monitor == nullptr && gdk_display_get_n_monitors(display) > 0)
      monitor = gdk_display_get_monitor(display, 0);
    if (monitor == nullptr) {
      response = FL_METHOD_RESPONSE(fl_method_success_response_new(nullptr));
    } else {
      GdkRectangle area;
      gdk_monitor_get_workarea(monitor, &area);
      g_autoptr(FlValue) size = size_value(area.width, area.height);
      response = FL_METHOD_RESPONSE(fl_method_success_response_new(size));
    }
  } else if (g_strcmp0(name, "resize") == 0) {
    FlValue* args = fl_method_call_get_args(call);
    int width = static_cast<int>(number_arg(args, "width"));
    int height = static_cast<int>(number_arg(args, "height"));
    if (width > 0 && height > 0) {
      gtk_window_set_default_size(self->window, width, height);
      gtk_window_resize(self->window, width, height);
    }
    response = FL_METHOD_RESPONSE(fl_method_success_response_new(nullptr));
  } else {
    response = FL_METHOD_RESPONSE(fl_method_not_implemented_response_new());
  }
  fl_method_call_respond(call, response, nullptr);
}

static gboolean window_configure_cb(GtkWidget* widget, GdkEvent* event,
                                    gpointer user_data) {
  MyApplication* self = MY_APPLICATION(user_data);
  if (self->window_channel == nullptr) return FALSE;
  int width = 0, height = 0;
  gtk_window_get_size(GTK_WINDOW(widget), &width, &height);
  GdkWindow* gdk_window = gtk_widget_get_window(widget);
  GdkWindowState state = gdk_window != nullptr ? gdk_window_get_state(gdk_window)
                                               : static_cast<GdkWindowState>(0);
  g_autoptr(FlValue) report = size_value(width, height);
  fl_value_set_string_take(report, "maximized",
                           fl_value_new_bool((state & GDK_WINDOW_STATE_MAXIMIZED) != 0));
  fl_value_set_string_take(report, "fullscreen",
                           fl_value_new_bool((state & GDK_WINDOW_STATE_FULLSCREEN) != 0));
  fl_value_set_string_take(report, "tiled",
                           fl_value_new_bool((state & GDK_WINDOW_STATE_TILED) != 0));
  fl_method_channel_invoke_method(self->window_channel, "resized", report,
                                  nullptr, nullptr, nullptr);
  return FALSE;
}

static void setup_window(MyApplication* self, GtkWindow* window, FlView* view) {
  self->window = window;
  g_object_add_weak_pointer(G_OBJECT(window), reinterpret_cast<gpointer*>(&self->window));
  FlEngine* engine = fl_view_get_engine(view);
  g_autoptr(FlStandardMethodCodec) codec = fl_standard_method_codec_new();
  self->window_channel = fl_method_channel_new(
      fl_engine_get_binary_messenger(engine), "maprisma_narrator/window",
      FL_METHOD_CODEC(codec));
  fl_method_channel_set_method_call_handler(self->window_channel,
                                            window_method_cb, self, nullptr);
  g_signal_connect(window, "configure-event", G_CALLBACK(window_configure_cb), self);
}

// Called when first Flutter frame received.
static void first_frame_cb(MyApplication* self, FlView* view) {
  gtk_widget_show(gtk_widget_get_toplevel(GTK_WIDGET(view)));
}

// Implements GApplication::activate.
static void my_application_activate(GApplication* application) {
  MyApplication* self = MY_APPLICATION(application);
  // One window: opening Maprisma Narrator again (panel menu, tray, launcher) brings it forward.
  GList* windows = gtk_application_get_windows(GTK_APPLICATION(application));
  if (windows != nullptr) {
    gtk_window_present(GTK_WINDOW(windows->data));
    return;
  }
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
  setup_window(self, window, view);

  gtk_widget_grab_focus(GTK_WIDGET(view));
}

// --toggle (the bar icon, as Maprisma Video Translator): close when the window is shown and
// focused, else show and focus it (or open it).
static void toggle_activated(GSimpleAction* action, GVariant* parameter, gpointer user_data) {
  GtkApplication* app = GTK_APPLICATION(user_data);
  GList* windows = gtk_application_get_windows(app);
  if (windows == nullptr) {
    g_application_activate(G_APPLICATION(app));
    return;
  }
  GtkWindow* window = GTK_WINDOW(windows->data);
  if (gtk_widget_get_visible(GTK_WIDGET(window)) && gtk_window_is_active(window)) {
    gtk_window_close(window);
    return;
  }
  gtk_window_present(window);
}

// Implements GApplication::local_command_line.
static gboolean my_application_local_command_line(GApplication* application,
                                                  gchar*** arguments,
                                                  int* exit_status) {
  MyApplication* self = MY_APPLICATION(application);
  // Strip out the first argument as it is the binary name; --toggle is ours, not Dart's.
  gboolean toggle = FALSE;
  GPtrArray* kept = g_ptr_array_new();
  for (gchar** arg = *arguments + 1; *arg != nullptr; arg++) {
    if (g_strcmp0(*arg, "--toggle") == 0) {
      toggle = TRUE;
    } else {
      g_ptr_array_add(kept, g_strdup(*arg));
    }
  }
  g_ptr_array_add(kept, nullptr);
  self->dart_entrypoint_arguments = reinterpret_cast<char**>(g_ptr_array_free(kept, FALSE));

  g_autoptr(GError) error = nullptr;
  if (!g_application_register(application, nullptr, &error)) {
    g_warning("Failed to register: %s", error->message);
    *exit_status = 1;
    return TRUE;
  }

  if (toggle && g_application_get_is_remote(application)) {
    g_action_group_activate_action(G_ACTION_GROUP(application), "toggle", nullptr);
    GDBusConnection* bus = g_application_get_dbus_connection(application);
    if (bus != nullptr) g_dbus_connection_flush_sync(bus, nullptr, nullptr);
    *exit_status = 0;
    return TRUE;
  }

  g_application_activate(application);
  *exit_status = 0;

  return TRUE;
}

// Implements GApplication::startup.
static void my_application_startup(GApplication* application) {
  // MyApplication* self = MY_APPLICATION(object);

  G_APPLICATION_CLASS(my_application_parent_class)->startup(application);
  g_autoptr(GSimpleAction) toggle = g_simple_action_new("toggle", nullptr);
  g_signal_connect(toggle, "activate", G_CALLBACK(toggle_activated), application);
  g_action_map_add_action(G_ACTION_MAP(application), G_ACTION(toggle));
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
  g_clear_object(&self->window_channel);
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
                                     G_APPLICATION_DEFAULT_FLAGS, nullptr));
}
