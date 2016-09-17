from DistUtilsExtra.auto import setup
from os import path

def find_var(var_name, *path_parts, **kwargs):
    with open(
            path.join(*path_parts),
            encoding=kwargs.get('encoding', 'utf-8')
            ) as f:
        for line in f:
            if line.startswith(var_name):
                # Call strip twice to remove whitespace then quote-marks
                # without having to define all white space (as newline may be
                # present at the end)
                return line[line.find('=')+1:].strip().strip("'\"")
                

PACKAGE_NAME = 'lightdm_kbswitch_greeter'
here = path.abspath(path.dirname(__file__))

with open(path.join(here, 'README.rst'), encoding='utf-8') as f:
    long_description = f.read()

# DistUtilsExtra.auto.setup uses the name kwarg to generate the path for each
# *.mo file compiled. Therefore use the same variable that is later used to
# set the text domain for gettext
name = find_var('APP_NAME', here, PACKAGE_NAME, 'greeter.py')

setup(
        name=name,
        version='0.1',
        description='Python and Gtk+ greeter for LightDM',
        long_description=long_description,
        url='git://github.com/bearvrrr/lightdm-kbswitch-greeter.git',
        author='Andrew Bates',
        author_email='andrew.bates@cantab.net',
        license='GPL',
        packages=[PACKAGE_NAME],
        install_requires=['gi'],
        data_files=[ # icons, *ui and *css files are detected automatcially
            ('/etc/lightdm', ['data/configs/lightdm-kbswitch-greeter.conf']),
            ('/usr/share/xgreeters', [
                'data/configs/lightdm-kbswitch-greeter.desktop'
                ]
            )
        ],
        entry_points={
            'console_scripts': [
                '{}={}.greeter:run'.format(name, PACKAGE_NAME)
            ],
        }
)
