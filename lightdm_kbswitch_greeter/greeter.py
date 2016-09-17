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

import sys
sys.path.append('/home/andrew/projects/lightdm-kbswitch-greeter')
from lightdm_kbswitch_greeter import greeter_background

import locale, gettext
_ = gettext.gettext

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('LightDM', '1')
from gi.repository import GLib, Gtk, Gdk, LightDM

import ctypes
from time import strftime
from configparser import ConfigParser
from typing import Any, Generator
import logging

APP_NAME             = 'lightdm-kbswitch-greeter'
LOCALE_DIR           = '/usr/share/locale'
CONFIG_FILE          = '/etc/lightdm/lightdm-kbswitch-greeter.conf'
APP_DATA_DIR         = '/usr/share/' + APP_NAME
UI_FILE              = APP_DATA_DIR + '/lightdm-kbswitch-greeter.ui'
CSS_APPLICATION_FILE = (APP_DATA_DIR +
        '/lightdm-kbswitch-greeter-application.css')
CONFIG_GROUP_DEFAULT = 'greeter'
DEFAULT_CLOCK_FORMAT = '%H:%M:%S'
DEFAULT_DATE_FORMAT  = '%A %d %B'
SESSION_LAST_USED    = '#last'

# mlockall flags
MCL_CURRENT = 1
MCL_FUTURE = 2

session_settings = dict()
login_window = None

clock = None
clock_format = None
date = None
date_format = None

language_menubutton = None
language_menu = None
keyboard_menubutton = None
keyboard_menu = None
session_menubutton = None
session_menu = None
a11y_menubutton = None
a11y_menu = None
power_menubutton = None
power_menu = None
suspend_menuitem = None
hibernate_menuitem = None
restart_menuitem = None
shutdown_menuitem = None

username_entry = None
password_entry = None

message_box = None
message_icon = None
message_text = None

power_window = None
power_title = None
power_text = None
power_ok_button = None
power_cancel_button = None
power_icon = None

# icon theming, defaults to revert after a11y callbacks
icon_theme = None
default_theme_name = None
default_icon_theme_name = None
default_font_name = None

greeter_config = None

# Helper functions
libc = ctypes.CDLL('libc.so.6', use_errno=True)

def mlockall(flags=MCL_CURRENT|MCL_FUTURE):
    result = libc.mlockall(flags)
    if result != 0:
        raise Exception('Cannot lock memmory, errno={}'.format(
                ctypes.get_errno()))


def draw_clock():
    clock.set_text(strftime(clock_format))
    date.set_text(strftime(date_format))
    return True


def get_layout_region(layout: LightDM.Layout) -> str:
    return layout.get_name().split()[0]


def generate_layout_menu_items(
        default_layout: LightDM.Layout
        ) -> Generator[Gtk.RadioMenuItem, Any, None]:
    layout_choices = set()

    kl = greeter_config.get('keyboard-layouts', None)
    if kl:
        layout_names = set()
        for i in kl.split(';'):
            if i: layout_names.add("\t".join(i.split()))
        lf = lambda l, lns=layout_names: l.get_name() in lns
        layout_choices = set(filter(lf, LightDM.get_layouts()))

    lr = greeter_config.get('keyboard-layout-regions', None)
    if lr:
        layout_regions = set()
        for i in lr.split(';'):
            if i: layout_regions.add(i.strip())

        if default_layout not in layout_choices:
            # Regions are being used to add groups of layouts. If the default
            # layout's region has not been explicitly added then add its group
            # for consistency
            layout_regions.add(get_layout_region(default_layout))

        rf = lambda l, lrs=layout_regions: get_layout_region(l) in lrs
        layout_choices = layout_choices.union(filter(rf, LightDM.get_layouts()))

    # For sanity, make sure default layout is always in the set
    layout_choices.add(default_layout)

    regions_items = dict()
    last_item = None
    for l in sorted(layout_choices, key=lambda lo: lo.get_name()):
        region = get_layout_region(l)
        l_desc = l.get_description()
        if region == l.get_name():
            # Switch countries and languages where language is written first
            pos = l_desc.find(' (')
            if pos != -1:
                l_desc = '{0} ({1})'.format(l_desc[pos+2:-1], l_desc[:pos])

        menu_item = Gtk.RadioMenuItem.new_with_label(None, l_desc)
        menu_item.lightdm_layout = l
        menu_item.connect('activate', change_keyboard_layout_cb)
        menu_item.join_group(last_item)
        if l == LightDM.get_layout(): menu_item.activate()

        if region not in regions_items:
            regions_items[region] = []
        regions_items[region].append(menu_item)
        last_item = menu_item
        
    region_keys = sorted(regions_items.keys())
    if len(region_keys) == 1:
        for mi in regions_items[region_keys[0]]:
            yield mi
    else:
        for rk in region_keys:
            mi = Gtk.MenuItem.new_with_label(rk)
            submenu = Gtk.Menu.new()
            mi.set_submenu(submenu)
            row = 0
            for sub_mi in regions_items[rk]:
                submenu.attach(sub_mi, 0, 1, row, row+1)
                row = row + 1
            yield mi
                

def get_language_description(language: LightDM.Language) -> str:
    return '{0}, {1} ({2})'.format(
            language.get_name(), language.get_territory(), language.get_code())


def resize_icons(icon_size):
    for i in (
            language_menubutton, keyboard_menubutton, session_menubutton,
            a11y_menubutton, power_menubutton):
        icon = i.get_child()
        icon.set_from_icon_name(icon.get_icon_name().icon_name, icon_size)


def show_message(text, message_type=None):
    message_text.set_text(text)

    if message_type == LightDM.MessageType.INFO:
        icon_name = 'emblem-important-symbolic'
    else:
        # Should be LightDM.MessageType.ERROR
        icon_name = 'dialog-error-symbolic'
    if icon_theme.has_icon(icon_name):
        message_icon.set_from_icon_name(icon_name, Gtk.IconSize.DIALOG)
                
    message_box.show_all()


def clear_entry():
    username_entry.set_text('')
    password_entry.set_text('')
    username_entry.grab_focus()

# Login window UI callbacks


def select_language_cb(widget):
    """Store the language code to set language when user logs in

    The LightDM.Greeter.set_language() method will only succeed if the user
    is already authenticated so it must be set after successful login
    """
    session_settings['language'] = widget.lightdm_language


def change_keyboard_layout_cb(widget):
    LightDM.set_layout(widget.lightdm_layout)


def select_session_cb(menu_item):
    global session_menubutton
    key = menu_item.lightdm_session_key
    if key == session_settings.get('session', None):
        return
    session_settings['session'] = key
    logging.debug('Setting session to %s', key)
    current_image = session_menubutton.get_child()
    current_icon_name, icon_size = current_image.get_icon_name()

    if key == SESSION_LAST_USED:
        icon_name = 'last-session_badge-symbolic'
        if icon_theme.has_icon(icon_name):
            current_image.set_from_icon_name(icon_name, icon_size)
            return
        
    for icon_name in [
            key.lower() + '_badge-symbolic',
            'applications-system-symbolic',
            'dialog-question-symbolic',
            'applications-system',
            'dialog-question'
            ]:
        if icon_name == current_icon_name: break
        if icon_theme.has_icon(icon_name):
            current_image.set_from_icon_name(icon_name, icon_size)
            break
    else:
        # No icon found, get default icon from another Gtk.MenuButton
        session_menubutton.remove(current_image)
        mb = Gtk.MenuButton.new()
        image = mb.get_child()
        del mb
        session_menubutton.add(image)
        image.show()


def a11y_font_cb(menu_item):
    if menu_item.get_active():
        settings = Gtk.Settings.get_default()
        font_name = settings.get_property('gtk-font-name')
        tokens = font_name.split()
        if len(tokens) > 1:
            size = int(tokens[-1])
            if size > 0:
                tokens[-1] = str(size + 5)
                font_name = ' '.join(tokens)
        settings.set_property('gtk-font-name', font_name)
        resize_icons(Gtk.IconSize.LARGE_TOOLBAR)
    else:
        Gtk.Settings.get_default().set_property('gtk-font-name', default_font_name)
        resize_icons(Gtk.IconSize.MENU)


def a11y_contrast_cb(menu_item):
    settings = Gtk.Settings.get_default()
    if menu_item.get_active():
        settings.set_property('gtk-theme-name', 'HighContrast')
        settings.set_property('gtk-icon-theme-name', 'HighContrast')
    else:
        settings.set_property('gtk-theme-name', default_theme_name)
        settings.set_property('gtk-icon-theme-name', default_icon_theme_name)


def power_menu_cb(widget):
    suspend_menuitem.set_sensitive(LightDM.get_can_suspend())
    hibernate_menuitem.set_sensitive(LightDM.get_can_hibernate())
    restart_menuitem.set_sensitive(LightDM.get_can_restart())
    shutdown_menuitem.set_sensitive(LightDM.get_can_shutdown())


def suspend_cb(widget):
    LightDM.suspend()


def hibernate_cb(widget):
    LightDM.hibernate()


def restart_cb(widget):
    if show_power_prompt('restart', 'view-refresh-symbolic'):
        LightDM.restart()


def shutdown_cb(widget):
    if show_power_prompt('shut down', 'system-shutdown-symbolic'):
        LightDM.shutdown()


def reset_login_cb(widget):
    for i in language_menu.get_children():
        if i.lightdm_language == LightDM.get_language():
            i.activate()
            break

    layout_found = False
    for i in keyboard_menu.get_children():
        sub_menu = i.get_submenu()
        if sub_menu:
            for si in sub_menu.get_children():
                if si.lightdm_layout == session_settings['default_layout']:
                    layout_found = True
                    si.activate()
                    break
            if layout_found: break
        else:
            if i.lightdm_layout == session_settings['default_layout']:
                i.activate()
                break

    for i in session_menu.get_children():
        if i.lightdm_session_key == session_settings['default_session']:
            i.activate()
            break
    clear_entry_cb(widget)


def clear_entry_cb(widget):
    clear_entry()


def username_key_press_event_cb(widget, event):
    if event.keyval == Gdk.KEY_Return:
        password_entry.grab_focus()
        return True


def password_key_press_event_cb(widget, event):
    if event.keyval == Gdk.KEY_Return:
        login_cb(widget)
        return True


def login_cb(widget):
    logging.debug('Login button clicked')
    login_window.set_sensitive(False)
    greeter.authenticate(username_entry.get_text())

# Power prompt UI


def show_power_prompt(action, icon_name):
    title = action.capitalize()
    message = ('Are you sure you want to close all programs and {0} the '
            'computer?').format(action)

    logged_in_users = 0
    for i in LightDM.UserList.get_users(LightDM.UserList.get_instance()):
        if i.get_logged_in():
            logged_in_users += 1

    if logged_in_users > 0:
        if logged_in_users == 1:
            warning = 'There is still 1 user logged in'
        else:
            warning = 'There are still {0} users logged in'.format(
                    logged_in_users)
        message = "<b>{0}</b>\n{1}".format(warning, message)

    power_title.set_label(title)
    power_text.set_markup(message)
    power_ok_button.set_label(title)
    power_icon.set_from_icon_name(icon_name, Gtk.IconSize.DIALOG)

    loop = GLib.MainLoop.new(None, False)
    power_window.loop = loop
    power_window.response = None

    language_menubutton.set_sensitive(False)
    keyboard_menubutton.set_sensitive(False)
    session_menubutton.set_sensitive(False)
    login_window.hide()
    power_window.show_all()
    power_ok_button.grab_focus()

    loop.run()
    response = power_window.response
    loop.unref()

    power_window.hide()
    login_window.show()
    language_menubutton.set_sensitive(True)
    keyboard_menubutton.set_sensitive(True)
    session_menubutton.set_sensitive(True)

    return response == Gtk.ResponseType.YES


def power_button_clicked_cb(button):
    loop = power_window.loop
    if loop.is_running():
        loop.quit()
    if button == power_ok_button:
        power_window.response = Gtk.ResponseType.YES
    else:
        power_window.response = Gtk.ResponseType.CANCEL


def power_window_key_press_event_cb(widget, event):
    if event.keyval == Gdk.KEY_Escape:
        power_button_clicked_cb(power_cancel_button)
        return True
    return False

# Widget positioning callbacks

def screen_overlay_get_child_position_cb(widget, allocation, user_data):
    # TODO: this method should position floating widgets not using halign and valign
    return

# end of Gtk callbacks

# Gtk signal handlers
handlers = {
    'a11y_font_cb': a11y_font_cb,
    'a11y_contrast_cb': a11y_contrast_cb,
    'power_menu_cb': power_menu_cb,
    'suspend_cb': suspend_cb,
    'hibernate_cb': hibernate_cb,
    'restart_cb': restart_cb,
    'shutdown_cb': shutdown_cb,
    'reset_login_cb': reset_login_cb,
    'clear_entry_cb': clear_entry_cb,
    'login_cb': login_cb,
    'username_key_press_event_cb': username_key_press_event_cb,
    'password_key_press_event_cb': password_key_press_event_cb,
    'power_window_key_press_event_cb': power_window_key_press_event_cb,
    'power_button_clicked_cb': power_button_clicked_cb,
    'screen_overlay_get_child_position_cb': screen_overlay_get_child_position_cb
}

# LightDM callbacks

def show_message_cb(lightdm_greeter, text, message_type):
    logging.debug('Recieved %s message', message_type)
    show_message(text, message_type)


def try_start_session(lightdm_greeter):
    logging.debug('Try to start session')
    if 'language' in session_settings:
        lightdm_greeter.set_language(session_settings['language'].get_code())
    if session_settings['session'] == SESSION_LAST_USED:
        logging.debug('Try to use last session')
        user_list = LightDM.UserList.get_instance()
        user = user_list.get_user_by_name(lightdm_greeter.get_authentication_user())
        logging.debug('User: %s', str(user))
        session = user.get_session()
        m = 'Session for user %s is %s'
        logging.debug(m, user.get_name(), session)
    else:
        session = session_settings['session']
        logging.debug('Session is %s', session)

    if not lightdm_greeter.start_session_sync(session):
        logging.debug("Failed to start session '%s'", session)
        show_message(_('Failed to start session'))
        login_window.set_sensitive(True)


def show_prompt_cb(lightdm_greeter, text, prompt_type):
    if lightdm_greeter.get_in_authentication():
        not_in_auth = ''
    else:
        not_in_auth = 'not '
    m = 'Prompt request for %s. Currently %sin authentication'
    logging.debug(m, str(prompt_type), not_in_auth)

    if lightdm_greeter.get_is_authenticated():
        try_start_session(lightdm_greeter)
    elif (prompt_type == LightDM.PromptType.SECRET and
            lightdm_greeter.get_in_authentication()):
        logging.debug('Sending password')
        lightdm_greeter.respond(password_entry.get_text())


def authentication_complete_cb(greeter):
    if greeter.get_is_authenticated():
        logging.debug('User authenticated, starting session')
        try_start_session(greeter)
    else:
        logging.debug('Login failed')
        show_message(_('Login failed'))
        clear_entry()
        login_window.set_sensitive(True)


def run():
    # Globals for callback functions and UI
    global session_settings
    global login_window 

    global clock 
    global clock_format 
    global date 
    global date_format 

    global language_menubutton 
    global language_menu 
    global keyboard_menubutton 
    global keyboard_menu 
    global session_menubutton 
    global session_menu 
    global a11y_menubutton 
    global a11y_menu 
    global power_menubutton 
    global power_menu 
    global suspend_menuitem 
    global hibernate_menuitem 
    global restart_menuitem 
    global shutdown_menuitem 

    global username_entry 
    global password_entry 

    global message_box 
    global message_icon 
    global message_text 

    global power_window 
    global power_title 
    global power_text 
    global power_ok_button 
    global power_cancel_button 
    global power_icon 

    global icon_theme 
    global default_theme_name 
    global default_icon_theme_name 
    global default_font_name 

    global greeter_config

    locale.setlocale(locale.LC_ALL, '')
    # allow Gtk.Builder to use translations for gettext
    locale.bindtextdomain(APP_NAME, LOCALE_DIR)
    gettext.bindtextdomain(APP_NAME, LOCALE_DIR)
    gettext.textdomain(APP_NAME)

    logging.basicConfig(level=logging.DEBUG,
            format=('+%(relativeCreated)dms [%(module)s] %(levelname)s '
                    '%(message)s'))

    # Prevent memory from being swapped out, as we are dealing with passwords
    try:
        mlockall()
    except Exception as e:
        logging.debug(str(e.args[0]))

    # LP: #1024882
    # https://bugs.launchpad.net/bugs/1024482
    GLib.setenv('GDK_CORE_DEVICE_EVENTS', '1', True)

    # LP: #1366534
    # https://bugs.launchpad.net/bugs/1366534
    GLib.setenv('NO_AT_BRIDGE', '1', True)

    # Connect signal handlers to LightDM
    global greeter
    greeter = LightDM.Greeter()
    greeter.connect('authentication-complete', authentication_complete_cb)
    greeter.connect('show-message', show_message_cb)
    greeter.connect('show-prompt', show_prompt_cb)
    greeter.connect_to_daemon_sync()

    full_config = ConfigParser()
    full_config.read(CONFIG_FILE)
    greeter_config = full_config[CONFIG_GROUP_DEFAULT]

    # Set clock and date strings
    clock_format = greeter_config.get('clock-format', DEFAULT_CLOCK_FORMAT)
    date_format = greeter_config.get('date-format', DEFAULT_DATE_FORMAT)

    # Set default cursor
    root_window = Gdk.get_default_root_window()
    root_window.set_cursor(
            Gdk.Cursor.new_from_name(Gdk.Display.get_default(), 'default'))

    # Set Gtk+ settings
    gtk_settings = Gtk.Settings.get_default()
    if greeter_config.get('theme-name', None):
        gtk_settings.set_property(
                'gtk-theme-name', greeter_config['theme-name'])
    default_theme_name = gtk_settings.get_property('gtk-theme-name')

    if greeter_config.get('icon-theme-name', None):
        gtk_settings.set_property(
                'gtk-icon-theme-name', greeter_config['icon-theme-name'])
    default_icon_theme_name = gtk_settings.get_property('gtk-icon-theme-name')

    if greeter_config.get('cursor-theme-name'):
        gtk_settings.set_property(
                'gtk-cursor-theme-name', greeter_config['cursor-theme-name'])

    if greeter_config.get('font-name', None):
        gtk_settings.set_property('gtk-font-name', greeter_config['font-name'])
    default_font_name = gtk_settings.get_property('gtk-font-name')

    if greeter_config.get('xft-antialias', None):
        gtk_settings.set_property(
                'gtk-xft-antialias', greeter_config['xft-antialias'])
    if greeter_config.get('xft-dpi', None):
        gtk_settings.set_property(
                'gtk-xft-dpi', 1024*greeter_config.getint('xft-dpi', 96))
    if greeter_config.get('xft-hintstyle', None):
        gtk_settings.set_property(
                'gtk-xft-hintstyle',
                greeter_config.getboolean('xft-hintstyle', False))
    if greeter_config.get('xft-rgba', None):
        gtk_settings.set_property('gtk-xft-rgba', greeter_config['xft-rgba'])

    icon_theme = Gtk.IconTheme.get_default()

    # Import the interface
    builder = Gtk.Builder()
    builder.add_from_file(UI_FILE)
    builder.connect_signals(handlers)

    # Login window
    login_window = builder.get_object('login_window')
    login_box = builder.get_object('login_box')
    username_entry = builder.get_object('username_entry')
    password_entry = builder.get_object('password_entry')
    session_controls = builder.get_object('session_controls')

    # Login window: Hostname and clock
    hostname_label = builder.get_object("hostname")
    hostname_label.set_text(LightDM.get_hostname())
    clock = builder.get_object('clock')
    date = builder.get_object('date')
    draw_clock()
    GLib.timeout_add_seconds(1, draw_clock)

    # Login window: initialise language menu
    language_menubutton = builder.get_object('language_menubutton')
    language_menu = builder.get_object('language_menu')

    if icon_theme.has_icon('preferences-desktop-locale-symbolic'):
        image = Gtk.Image.new_from_icon_name(
                'preferences-desktop-locale-symbolic', Gtk.IconSize.MENU)
    else:
        image = Gtk.Image.new_from_icon_name(
                'preferences-desktop-locale', Gtk.IconSize.MENU)
    image.show()
    language_menubutton.add(image)

    row = 0
    last_item = None
    for i in LightDM.get_languages():
        menu_item = Gtk.RadioMenuItem.new_with_label(
                            None, get_language_description(i))
        menu_item.lightdm_language = i
        menu_item.connect('activate', select_language_cb)
        menu_item.join_group(last_item)
        if i == LightDM.get_language(): menu_item.activate()
        language_menu.attach(menu_item, 0, 1, row, row+1)
        row += 1
        last_item = menu_item
    
    language_menu.show_all()
    language_menubutton.set_popup(language_menu)

    # Login window: initialise keyboard menu

    # LightDM.get_layout() resets the keyboard layout to default
    # so only call this once
    session_settings['default_layout'] = LightDM.get_layout()
    dkl = greeter_config.get('default-keyboard-layout', None)
    if dkl:
        logging.debug('Setting default layout...')
        dkl = "\t".join(dkl.split())
        for i in LightDM.get_layouts():
            if dkl == i.get_name():
                m = "Set default keyboard layout to: '%s' %s"
                logging.debug(m, i.get_name(), str(i))
                session_settings['default_layout'] = i
                LightDM.set_layout(session_settings['default_layout'])
                break

    keyboard_menubutton = builder.get_object('keyboard_menubutton')
    keyboard_menu = builder.get_object('keyboard_menu')

    if icon_theme.has_icon('input-keyboard-symbolic'):
        image = Gtk.Image.new_from_icon_name(
                'input-keyboard-symbolic', Gtk.IconSize.MENU)
    else:
        image = Gtk.Image.new_from_icon_name(
                'input-keyboard', Gtk.IconSize.MENU)
    image.show()
    keyboard_menubutton.add(image)
    row = 0
    for menu_item in generate_layout_menu_items(
            session_settings['default_layout']):
        keyboard_menu.attach(menu_item, 0, 1, row, row+1)
        row += 1
    keyboard_menu.show_all()
    keyboard_menubutton.set_popup(keyboard_menu)

    # Login window: initilaise session menu
    default_session = greeter_config.get(
            'default-session', str(greeter.get_default_session_hint()))
    session_menubutton = builder.get_object('session_menubutton')
    session_menu = builder.get_object('session_menu')

    # select_session_cb only changes icon, not size so explicity set size of
    # button icon here
    session_menu_icon = session_menubutton.get_child()
    session_menu_icon.set_from_icon_name(
            session_menu_icon.get_icon_name().icon_name, Gtk.IconSize.MENU)

    menu_item = Gtk.RadioMenuItem.new_with_label(None, 'Last used session')
    menu_item.lightdm_session_key = SESSION_LAST_USED
    menu_item.connect('activate', select_session_cb)
    menu_item.join_group(None)
    session_menu.attach(menu_item, 0, 1, 0, 1)
    # Make sure first item is selected in case default-session is not properly
    # defined in configuration
    menu_item.activate()

    last_item = menu_item
    row = 1
    for i in LightDM.get_sessions():
        menu_item = Gtk.RadioMenuItem.new_with_label(None, i.get_name())
        menu_item.lightdm_session_key = i.get_key()
        menu_item.connect('activate', select_session_cb)
        menu_item.join_group(last_item)
        session_menu.attach(menu_item, 0, 1, row, row+1)
        if default_session.lower() == i.get_key().lower():
            menu_item.activate()
            session_settings['default_session'] = i.get_key()
        row += 1
        last_item = menu_item
    session_menu.show_all()
    session_menubutton.set_popup(session_menu)

    # Login window: initilaise a11y menu
    a11y_menubutton = builder.get_object('a11y_menubutton')
    a11y_menu = builder.get_object('a11y_menu')

    if icon_theme.has_icon('preferences-desktop-accessibility-symbolic'):
        image = Gtk.Image.new_from_icon_name(
                'preferences-desktop-accessibility-symbolic', Gtk.IconSize.MENU)
    else:
        image = Gtk.Image.new_from_icon_name(
                'preferences-desktop-accessibility', Gtk.IconSize.MENU)
    image.show()
    a11y_menubutton.add(image)
    a11y_menubutton.set_popup(a11y_menu)
    a11y_menubutton.show_all()

    # Login window: initialise power menu
    power_menubutton = builder.get_object('power_menubutton')
    power_menu = builder.get_object('power_menu')
    suspend_menuitem = builder.get_object('suspend_menuitem')
    hibernate_menuitem = builder.get_object('hibernate_menuitem')
    restart_menuitem = builder.get_object('restart_menuitem')
    shutdown_menuitem = builder.get_object('shutdown_menuitem')
    if icon_theme.has_icon('system-shutdown-symbolic'):
        image = Gtk.Image.new_from_icon_name(
                'system-shutdown-symbolic', Gtk.IconSize.MENU)
    else:
        image = Gtk.Image.new_from_icon_name(
                'system-shutdown', Gtk.IconSize.MENU)
    image.show()
    power_menubutton.add(image)
    power_menubutton.set_popup(power_menu)
    power_menubutton.show_all()

    # Login window: initialise message box
    message_box = builder.get_object('message_box')
    message_icon = builder.get_object('message_icon')
    message_text = builder.get_object('message_text')

    # Power window
    power_window = builder.get_object('power_window')
    power_title = builder.get_object('power_title')
    power_text = builder.get_object('power_text')
    power_ok_button = builder.get_object('power_ok_button')
    power_cancel_button = builder.get_object('power_cancel_button')
    power_icon = builder.get_object('power_icon')
    
    # Add login and power windows to overlay
    screen_overlay = builder.get_object('screen_overlay')
    screen_overlay.add_overlay(login_window)
    screen_overlay.add_overlay(power_window)

    # Accelerators
    Gtk.AccelMap.add_entry('<Login>/a11y/font', Gdk.KEY_F1, 0)
    Gtk.AccelMap.add_entry('<Login>/a11y/contrast', Gdk.KEY_F2, 0)
    Gtk.AccelMap.add_entry(
            '<Login>/power/shutdown', Gdk.KEY_F4, Gdk.ModifierType.MOD1_MASK)

    # CSS
    try:
        css_provider = Gtk.CssProvider()
        with open(CSS_APPLICATION_FILE, 'rb') as css_file:
            css_provider.load_from_data(css_file.read())
            Gtk.StyleContext.add_provider_for_screen(
                    Gdk.Screen.get_default(),
                    css_provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    except FileNotFoundError as e:
        m = "Could not load application css file '%s': %s"
        logging.debug(m, e.filename, e.strerror)

    background = greeter_background.GreeterSurface(
            full_config, CONFIG_GROUP_DEFAULT, screen_overlay)
    background.add_accel_group(builder.get_object('a11y_accel_group'))
    background.add_accel_group(builder.get_object('power_accel_group'))
    login_window.show_all()
    message_box.hide()
    screen_overlay.show()

    username_entry.grab_focus()
    Gtk.main()


if __name__ == '__main__':
    run()
