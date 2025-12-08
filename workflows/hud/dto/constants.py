from enum import Enum


HUD_NAME_MOUSE_BINDINGS = 'MOUSE BINDINGS'

class AppExe(str, Enum):
    DOCKER = "docker.exe"
    DOCKER_DESKTOP = "Docker Desktop.exe"
    DOCKER_BACKEND = "com.docker.backend.exe"
    DOCKER_BUILD = "com.docker.build.exe"

    CHROME = "chrome.exe"
    PYCHARM = "pycharm64.exe"
    SUBLIME_TEXT = "sublime_text.exe"
    RAINMETER = "Rainmeter.exe"
    MATTERMOST = "Mattermost.exe"
    SPOTIFY = "Spotify.exe"
    WEBEX = "WebexHost.exe"
    ICUE = "iCUE.exe"
    CELERY = "celery.exe"
    PYTHON = "python.exe"
    TERMINAL = "OpenConsole.exe"
    CMD = "cmd.exe"
    EXPLORER = "explorer.exe"
    # add more as needed...


# Example: profile names (iCUE / macros / HUD profiles etc.)
class Profile(str, Enum):
    BASE_MACROS_TO_COPY = "BASE_MACROS_TO_COPY_"
    BASE = "BASE_TO_COPY_"
    BROWSER = "Chrome"
    MARKDOWN = "Markdown"
    NAVIGATION = "Navigation"
    TEXT_EDITOR = "Notes"
    CODING = "PyCharm"
    CALL = "WEBEX"


# Map applications → profiles
APP_TO_PROFILE: dict[AppExe, Profile] = {

    # some sensible defaults (tweak however you want)
    AppExe.PYCHARM: Profile.CODING,
    AppExe.SUBLIME_TEXT: Profile.TEXT_EDITOR,
    AppExe.CELERY: Profile.NAVIGATION,
    AppExe.PYTHON: Profile.NAVIGATION,
    AppExe.CHROME: Profile.BROWSER,
    AppExe.EXPLORER: Profile.BROWSER,
    AppExe.WEBEX: Profile.CALL,
    AppExe.RAINMETER: Profile.BASE,
    AppExe.TERMINAL: Profile.BASE,
    AppExe.CMD: Profile.BASE,
}

