import shutil
import functools
import filecmp
import time
import subprocess
import winsound

from configparser import ConfigParser
import os

import shlex

WAIT_SECS_DEFAULT = 10

frequency = 1200
duration = 300


def initialize_hud_configuration(config: dict,
                                 hud_item_name: str,
                                 template_name='base.ini',
                                 include_notes_bin=True,
                                 notes_file='dump.txt',
                                 new_sections_dict=None,
                                 reset_alerts_secs=10,
                                 play_sound=True,
                                 always_alert=False
                                 ):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            """
            :param args:
            :param kwargs:
            :return:
            https://betterprogramming.pub/python-celery-best-practices-ae182730bb81
            """
            try:
                config_ini = ConfigHelperRainmeter()
                skin_name = config['skin_name']
                static_path = config['static_path']
                write_skin_path = os.path.join(config['write_skin_to_path'], skin_name)

                if not os.path.exists(write_skin_path):
                    #  copy resources
                    src = os.path.join(static_path, '@Resources')
                    dest = os.path.join(write_skin_path, '@Resources')
                    shutil.copytree(src, dest)

                    #  copy options
                    src = os.path.join(static_path, 'Options')
                    dest = os.path.join(write_skin_path, 'Options')
                    shutil.copytree(src, dest)

                ini_path = os.path.join(write_skin_path, hud_item_name.replace(' ', ''))
                note_file = os.path.join(ini_path, notes_file)
                if not os.path.exists(ini_path):
                    os.makedirs(ini_path)
                    if include_notes_bin:
                        src = os.path.join(static_path, 'bin', 'LuaTextFile.lua')
                        dest = os.path.join(ini_path, 'LuaTextFile.lua')
                        shutil.copyfile(src, dest)
                        with open(note_file, 'w'):
                            pass

                short_hud_name = hud_item_name.replace(' ', '')
                file_ini_new = '{0}.ini'.format(short_hud_name)
                new_ini = os.path.join(ini_path, file_ini_new)
                template_path_file = os.path.join(static_path, template_name)
                config_ini.template_config_file = template_path_file
                config_ini.read_template_configuration()

                if new_sections_dict is not None:
                    for section in new_sections_dict:
                        file_ini_new = '{0}.ini'.format(short_hud_name)
                        config_ini.add_section(section)

                notes_dump = func(ini=config_ini, *args, **kwargs)
                tmp_note = os.path.join(ini_path, 'tmp.txt')
                tmp = NotesTextHelperRainmeter(tmp_note)
                tmp.write(notes_dump)

                #  check if notes_file = dump.txt had changed
                try:
                    updated = not filecmp.cmp(note_file, tmp_note)
                    os.remove(tmp_note)
                except Exception:
                    updated = False

                if always_alert:
                    updated = True

                note = NotesTextHelperRainmeter(note_file)
                note.write(notes_dump)

                config_ini['meterTitle']['text'] = hud_item_name

                replace_border_value = 'Stroke Color [#alertColor]' if updated else 'Stroke Color [#warnColor]'
                replace_border = config_ini['MeterBackground']['shape'].replace('Stroke Color [#darkColor]',
                                                                                replace_border_value)
                config_ini['MeterBackground']['shape'] = replace_border

                config_ini.save_to_new_file(ini_file_name=new_ini)

                if updated and play_sound:
                    winsound.Beep(frequency, duration)

                cmd_act_cfg = '"{0}" !ActivateConfig "{1}\\{2}" "{3}"'\
                    .format(config['bin_path'], skin_name, short_hud_name, file_ini_new)
                subprocess.call(shlex.split(cmd_act_cfg))

                cmd_refresh_app = '"{0}" !RefreshApp'.format(config['bin_path'])
                subprocess.call(shlex.split(cmd_refresh_app))

                wait = reset_alerts_secs if updated else WAIT_SECS_DEFAULT
                #  reset borders after some timeout
                time.sleep(wait)
                reset_config_ini = ConfigHelperRainmeter(new_ini)
                reset_config_ini.read_template_configuration()
                replace_border = reset_config_ini['MeterBackground']['shape'].replace(replace_border_value,
                                                                                      'Stroke Color [#darkColor]')
                reset_config_ini['MeterBackground']['shape'] = replace_border
                reset_config_ini.save_to_new_file(new_ini)

                cmd_act_cfg = '"{0}" !ActivateConfig "{1}\\{2}" "{3}"'\
                    .format(config['bin_path'], skin_name, short_hud_name, file_ini_new)
                subprocess.call(shlex.split(cmd_act_cfg))

                cmd_refresh_app = '"{0}" !RefreshApp'.format(config['bin_path'])
                subprocess.call(shlex.split(cmd_refresh_app))

            except Exception as e:
                raise Exception("Failed hud initialization! {0}".format(e))

        return wrapper

    return decorator


class ConfigHelperRainmeter(ConfigParser):

    def __init__(self, template_config_file=None):
        super().__init__()
        self.template_config_file = template_config_file

    def read(self, filenames, encoding=None):
        super().read(filenames=filenames, encoding=encoding)

    def read_template_configuration(self):
        return self.read(self.template_config_file)

    def save_to_new_file(self, ini_file_name):
        with open(ini_file_name, 'w') as configfile:
            self.write(configfile)


class NotesTextHelperRainmeter:

    def __init__(self, file_name_txt):
        self.file_name_txt = file_name_txt

    def write(self, stream):
        with open(self.file_name_txt, "w") as f:
            f.write(stream)
