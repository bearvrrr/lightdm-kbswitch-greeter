# lightdm-kbswitch-greeter A Gtk3 based greeter for LightDM
# Copyright (C) 2016 Andrew Bates
# Author Andrew Bates <andrew.bates@cantab.net>
# Based on lightdm-gtk-greeter Copyright (C) 2010-2011 Robert Ancell
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import gi
gi.require_version('Gtk', '3.0')

from gi.repository import GObject, Gtk, Gdk, GdkPixbuf
import os
from configparser import ConfigParser
from enum import Enum
from typing import List
import logging

BACKGROUND_TYPE_SKIP = '#skip'
CONFIG_MONITOR_PREFIX = 'monitor:'

class ScalingMode(Enum):
    SOURCE = '#source'
    STRETCHED = '#stretched'
    ZOOMED = '#zoomed'


class BackgroundImageConfigError(ValueError):
    pass


class MonitorError(Exception):
    pass


class PixbufCache:
    def __init__(self):
        self._cache = {}

    def get(self, image_path: str, mode: ScalingMode,
            width:int, height:int) -> GdkPixbuf.Pixbuf:
        """Return a GdkPixbuf.Pixbuf that has been zoomed, stretched or
        cropped to width and height
        """
        key = ':'.join([image_path, mode.value, str(width), str(height)])
        if key in self._cache.keys():
            return self._cache[key]

        try:
            pixbuf = self._cache[image_path]
        except KeyError:
            # Raises GLib.Error if fails
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path)
            self._cache[image_path] = pixbuf

        if mode == ScalingMode.ZOOMED:
            offset_x = 0
            offset_y = 0
            p_width = pixbuf.get_width()
            p_height = pixbuf.get_height()
            scale_x = width / p_width
            scale_y = height / p_height

            if scale_x < scale_y:
                scale_x = scale_y
                offset_x = (width - (p_width * scale_x)) / 2
            else:
                scale_y = scale_x
                offset_y = (height - (p_height * scale_y)) / 2

            scaled = GdkPixbuf.Pixbuf.new(
                    GdkPixbuf.Colorspace.RGB, True,
                    pixbuf.get_bits_per_sample(), width, height)

            pixbuf.composite(scaled,
                    0, 0, width, height,
                    offset_x, offset_y, scale_x, scale_y,
                    GdkPixbuf.InterpType.BILINEAR, 255)

        elif mode == ScalingMode.STRETCHED:
            scaled = pixbuf.scale_simple(width, height,
                    GdkPixbuf.InterpType.BILINEAR)
        else:
            scaled = pixbuf
        
        self._cache[key] = scaled
        return scaled


class BackgroundImageConfig:
    """Configuration to specify path and scaling for an image file to be used
    as a background"""
    def __init__(self, image_spec):
        for mode in ScalingMode:
            prefix = mode.value + ':'
            if prefix == image_spec[0:len(prefix)]:
                self._scaling_mode = mode
                image_path = image_spec[len(prefix):]
                break
        else:
            self._scaling_mode = ScalingMode.ZOOMED
            image_path = image_spec

        if not os.path.exists(image_path):
            m = "Path '{0}' does not exist".format(image_path)
            raise BackgroundImageConfigError(m)
        self._path = image_path

    @property
    def path(self):
        """Path to image file"""
        return self._path

    @property
    def scaling_mode(self):
        """Member of ScalingMode"""
        return self._scaling_mode


class MonitorConfig:
    """Stores background configuration for a monitor"""
    def __init__(self, config=None):
        self._background = Gdk.RGBA(0,0,0,1)
        if not config: return
        if not config.get('background', None): return
        
        if config['background'] == BACKGROUND_TYPE_SKIP:
            self._background = None
        else:
            set_color_success = self._background.parse(config['background'])
            if not set_color_success:
                try:
                    bg = BackgroundImageConfig(config['background'])
                    self._background = bg
                except BackgroundImageConfigError as e:
                    m = ("Invalid monitor config option background: '%s' "
                            "(%s). Using default background instead")
                    logging.debug(m, config['background'], e.args[0])

    @property
    def background(self):
        """The background property will be one of three types:
        None: if the monitor should be skipped and not have any rendering
        GdkRGBA: if the monitor background is a single flat colour
        BackgroundImageConfig: if the monitor background should use an image
        """
        return self._background


class Monitor:
    def __init__(self, number, greeter_surface, pixbuf_cache=None):
        self._screen = greeter_surface.screen
        if number >= self._screen.get_n_monitors():
            m = ('No monitor number #{0} exists (valid numbers range from 0 '
                    'to {1}')
            raise MonitorError(m.format(number, self._screen.get_n_monitors()))
        self._number = number
        self._name = self._screen.get_monitor_plug_name(number)
        
        if self.name in greeter_surface.configs.keys():
            self._config = greeter_surface.configs[self.name]
        elif self.number in greeter_surface.configs.keys():
            self._config = greeter_surface.configs[self.number]
        else:
            m = ('no configuration set for monitor %s, #%d. Using default')
            logging.debug(m, self.printable_name, self.number)
            self._config = greeter_surface.default_config

        self._geometry = self._screen.get_monitor_geometry(self.number)
        primary = ''
        if self.number == self._screen.get_primary_monitor():
            primary = ' primary'
        logging.debug('Monitor: %s #%d (%dx%d at %dx%d)%s',
                self.printable_name, self.number,
                self._geometry.width, self._geometry.height,
                self._geometry.x, self._geometry.y, primary)

        self._init_background(greeter_surface, pixbuf_cache)

    @property
    def number(self):
        return self._number

    @property
    def name(self):
        return self._name

    @property
    def printable_name(self):
        if self.name: return self.name
        return '<unknown>'

    @property
    def is_enabled(self):
        """Boolean True if monitor can display interface"""
        return bool(self._window)

    @property
    def background(self):
        return self._background

    def add_accel_group(self, accel_group):
        if self._window:
            self._window.add_accel_group(accel_group)

    def contains_coordinate(self, x: int, y: int) -> bool:
        if (x >= self._geometry.x and
                x < self._geometry.x + self._geometry.width and
                y >= self._geometry.y and
                y < self._geometry.y + self._geometry.height):
            return True
        return False
        
    def force_config(self, config, pixbuf_cache=None):
        """Override monitor config"""
        logging.debug('Explicitly set config for monitor %s #%d',
                self.printable_name, self.number)
        self._config = config
        self._init_background(pixbuf_cache)

    def set_active(self, greeter_surface):
        """Move login interface to this monitor"""
        if not self._window:
            m = 'Cannot set monitor {0} #{1} as active. No background present'
            raise MonitorError(m.format(self.printable_name, self.number))

        # old_parent may be None or Gtk.Window
        old_parent = greeter_surface.child.get_property('parent')
        if self._window is not old_parent:
            logging.debug('Setting monitor %s #%d as active',
                    self.printable_name, self.number)
            # Save focus
            focus_widget, editable_pos = greeter_surface.focus

            # Reparent interface
            if old_parent:
                old_parent.remove(greeter_surface.child)
            self._window.add(greeter_surface.child)

            # Restore focus
            if focus_widget:
                focus_widget.grab_focus()
                if editable_pos > -1:
                    focus_widget.set_position(editable_pos)

    def enter_notify_event_cb(self, window, event, greeter_surface):
        self.set_active(greeter_surface)
        return False

    def draw_monitor_background_cb(self, widget, cr):
        if not self._background: return
        if isinstance(self._background, Gdk.RGBA):
            cr.rectangle(0, 0, self._geometry.width, self._geometry.height)
            Gdk.cairo_set_source_rgba(cr, self._config.background)
            cr.fill()
        elif isinstance(self._background, GdkPixbuf.Pixbuf):
            Gdk.cairo_set_source_pixbuf(cr, self._background, 0, 0)
            cr.paint()
        return False

    def _init_background(self, greeter_surface, pixbuf_cache=None):
        self._window = None
        self._background = None
        if not self._config.background: return

        bg = self._config.background
        if isinstance(bg, Gdk.RGBA):
            self._background = bg
        elif isinstance(bg, BackgroundImageConfig):
            if not pixbuf_cache:
                pixbuf_cache = PixbufCache()
            self._background = pixbuf_cache.get(bg.path, bg.scaling_mode,
                    self._geometry.width, self._geometry.height)
        else:
            m = "Invalid background set in config: '{0}'"
            raise MonitorError(m.format(str(self._config.background)))

        self._window = Gtk.Window(Gtk.WindowType.TOPLEVEL)
        self._window.set_type_hint(Gdk.WindowTypeHint.DESKTOP)
        self._window.set_keep_below(True)
        self._window.set_resizable(False)
        self._window.set_app_paintable(True)
        self._window.set_screen(self._screen)
        self._window.set_size_request(
                self._geometry.width, self._geometry.height)
        self._window.move(self._geometry.x, self._geometry.y)
        self._window.show()
        self._window.connect('draw', self.draw_monitor_background_cb)
        self._window.connect('enter-notify-event', self.enter_notify_event_cb,
                greeter_surface)

        if self.name:
            self._window.set_name('monitor-{0}'.format(self.name))
        else:
            self._window.set_name('monitor-{0}'.format(self.number))

        for i in greeter_surface.accel_groups:
            self.add_accel_group(i)


class GreeterSurface(GObject.GObject):
    def __init__(self,
            config: ConfigParser,
            default_config_section: str,
            child: Gtk.Widget) -> None:
        """
        Keyword arguments:
        config -- default and per monitor configuration
        default_config_section -- name of the config section to use as default
        child -- widget to display on the active monitor
        """
        GObject.GObject.__init__(self)
        self._child = child
        self._child.connect('destroy', self.child_destroyed_cb)
        self._accel_groups = set()

        self._default_config = MonitorConfig(config[default_config_section])

        self._configs = {}
        for section in config.sections():
            if section.find(CONFIG_MONITOR_PREFIX) != 0: continue
            name = section[len(CONFIG_MONITOR_PREFIX):].strip()
            self._configs[name] = MonitorConfig(config[section])

        self._screen = Gdk.Screen.get_default()
        logging.debug(
                'Connecting to screen %s (%dx%dpx, %dx%dmm)',
                str(self._screen), self._screen.width(), self._screen.height(),
                self._screen.width_mm(), self._screen.height_mm())
        self._refresh_monitors()
        self._screen.connect('monitors-changed', self.monitors_changed_cb)

    @property
    def screen(self) -> Gdk.Screen:
        return self._screen

    @property
    def child(self) -> Gtk.Widget:
        return self._child

    @property
    def focus(self):
        """Tuple of the focused widget or None if no widget focused and the
        cursor position if the focused widget is editable or -1 otherwise
        """
        focus_widget = None
        editable_pos = -1

        window = self._child.get_property('parent')
        if window:
            focus_widget = window.get_focus()
            if isinstance(focus_widget, Gtk.Editable):
                editable_pos = focus_widget.get_position()

        return focus_widget, editable_pos

    @property
    def accel_groups(self):
        return self._accel_groups

    @property
    def default_config(self) -> MonitorConfig:
        return self._default_config

    @property
    def configs(self) -> List[MonitorConfig]:
        return self._configs

    def child_destroyed_cb(self, child_widget):
        self._child = None
    
    def monitors_changed_cb(self, screen):
        if screen is not self._screen:
            m = ("screen parameter supplied '{0}' is not the one that "
                    "GreeterSurface object '{1}' is associated with")
            raise GreeterSurfaceError(m.format(screen, self), screen)
        logging.debug(
                'Monitors changed for screen %s',
                str(self._screen))
        self._refresh_monitors()

    def add_accel_group(self, accel_group):
        if accel_group not in self._accel_groups:
            self._accel_groups.add(accel_group)
            for i in self._enabled_monitors:
                i.add_accel_group(accel_group)

    def _refresh_monitors(self):
        logging.debug(
                'Setting monitor backgrounds for screen %s',
                str(self._screen))

        self._monitors = [] # all monitors
        self._enabled_monitors = [] # monitors we can draw on
        first_not_skipped_monitor = None
        pixbuf_cache = PixbufCache()

        num_monitors = self._screen.get_n_monitors()
        logging.debug('Monitors found: %d', num_monitors)

        for i in range(0, num_monitors):
            monitor = Monitor(i, self, pixbuf_cache)
            self._monitors.append(monitor)
            if not monitor.is_enabled:
                # No background implying skip this monitor
                if i < num_monitors - 1 or first_not_skipped_monitor:
                    # Monitors left to check so can actually skip
                    logging.debug('Skipping monitor %s #%d',
                            monitor.printable_name, monitor.number)
                    continue
                m = ('Monitor %s #%d cannot be skipped. Using default '
                        'configuration for it')
                logging.debug(m, monitor.printable_name, monitor.number)

                if self.default_config.background:
                    monitor.force_config(self.default_config)
                else:
                    # default_config has skip background type so force
                    # config that will render
                    monitor.force_config(MonitorConfig())

            logging.debug('Monitor %s #%d is enabled',
                    monitor.printable_name, monitor.number)
            self._enabled_monitors.append(monitor)
            if not first_not_skipped_monitor:
                first_not_skipped_monitor = monitor

        x, y = self._get_cursor_position()
        for monitor in self._enabled_monitors:
            if monitor.contains_coordinate(x, y):
                m = ('Monitor %s #%d contains the cursor. '
                        'Setting it as the active monitor.')
                logging.debug(m, monitor.printable_name, monitor.number)
                monitor.set_active(self)
                break
        else:
            m = ('Cursor is not in area of enable monitors. '
                    'using monitor %s #%d')
            logging.debug(m, first_not_skipped_monitor.printable_name,
                    first_not_skipped_monitor.number)
            first_not_skipped_monitor.set_active(self)

    def _get_cursor_position(self):
        display = self.screen.get_display()
        device = display.get_device_manager().get_client_pointer()
        _, x, y = device.get_position()
        return x, y
