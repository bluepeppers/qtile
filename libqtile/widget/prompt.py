import time, os, glob, string
from .. import hook, bar, manager, xkeysyms, xcbq
import base
try:
    import cPickle as pickle
except ImportError:
    import pickle

class NullCompleter:
    def actual(self, qtile):
        return None

    def complete(self, txt):
        return txt

class GroupCompleter:
    def __init__(self, qtile):
        self.qtile = qtile
        self.thisfinal = None
        self.lookup, self.offset = None, None

    def actual(self):
        """
            Returns the current actual value.
        """
        return self.thisfinal

    def reset(self):
        self.lookup = None
        self.offset = -1

    def complete(self, txt):
        """
            Returns the next completion for txt, or None if there is no completion.
        """
        txt = txt.lower()
        if not self.lookup:
            self.lookup = []
            for group in self.qtile.groupMap.keys():
                if group.lower().startswith(txt):
                    self.lookup.append((group, group))

            self.lookup.sort()
            self.offset = -1
            self.lookup.append((txt, txt))

        self.offset += 1
        if self.offset >= len(self.lookup):
            self.offset = 0
        ret = self.lookup[self.offset]
        self.thisfinal = ret[1]
        return ret[0]


class CommandCompleter:
    DEFAULTPATH = "/bin:/usr/bin:/usr/local/bin"
    def __init__(self, qtile, _testing=False):
        """
            _testing: disables reloading of the lookup table to make testing possible.
        """
        self.lookup, self.offset = None, None
        self.thisfinal = None
        self._testing = _testing

    def actual(self):
        """
            Returns the current actual value.
        """
        return self.thisfinal

    def executable(self, fpath):
        return os.access(fpath, os.X_OK)

    def reset(self):
        self.lookup = None
        self.offset = -1

    def complete(self, txt):
        """
            Returns the next completion for txt, or None if there is no completion.
        """
        if not self.lookup:
            if not self._testing:
                # Lookup is a set of (display value, actual value) tuples.
                self.lookup = []
                if txt and txt[0] in "~/":
                    path = os.path.expanduser(txt)
                    if os.path.isdir(path):
                        files = glob.glob(os.path.join(path, "*"))
                        prefix = txt
                    else:
                        files = glob.glob(path+"*")
                        prefix = os.path.dirname(txt)
                    prefix = prefix.rstrip("/") or "/"
                    for f in files:
                        if self.executable(f):
                            display = os.path.join(prefix, os.path.basename(f))
                            if os.path.isdir(f):
                                display += "/"
                            self.lookup.append((display, f))
                else:
                    dirs = os.environ.get("PATH", self.DEFAULTPATH).split(":")
                    for didx, d in enumerate(dirs):
                        try:
                            for cmd in glob.glob(os.path.join(d, "%s*"%txt)):
                                if self.executable(cmd):
                                    self.lookup.append(
                                        (
                                            os.path.basename(cmd),
                                            cmd
                                        ),

                                    )
                        except OSError:
                            pass
            self.lookup.sort()
            self.offset = -1
            self.lookup.append((txt, txt))
        self.offset += 1
        if self.offset >= len(self.lookup):
            self.offset = 0
        ret = self.lookup[self.offset]
        self.thisfinal = ret[1]
        return ret[0]


class History(list):
    current_pos = 0
    original_line = None
    _keysyms = ["Up", "Down", "Page_Up", "Page_Down"]
    keysyms = [xkeysyms.keysyms[val] for val in _keysyms]

    def handleKeySym(self, keysym, txt):
        if self.original_line is None:
            self.original_line = txt

        if not self:
            return
        print self.current_pos, len(self), self.original_line
        if keysym == xkeysyms.keysyms["Up"]:
            if self.current_pos < len(self):
                self.current_pos += 1
            else:
                return
        elif keysym == xkeysyms.keysyms["Down"]:
            if self.current_pos > 0:
                self.current_pos -= 1
            else:
                return
        elif keysym == xkeysyms.keysyms["Page_Up"]:
            self.current_pos = len(self)
        elif keysym == xkeysyms.keysyms["Page_Down"]:
            self.current_pos = 0

        if self.current_pos == 0:
            return self.original_line
        else:
            return self[self.current_pos - 1]

    def cleanup(self):
        return


class TransientHistory(History):
    def __init__(self, qtile, name):
        self.qtile = qtile


class PersistentHistory(History):
    def __init__(self, qtile, name):
        print "Persistent History"
        self.qtile = qtile
        data_dir = os.environ.get("XDG_DATA_HOME") or \
            (os.environ["HOME"] + "/.local/share")
        qtile_dir = data_dir + "/qtile"
        if not os.path.exists(qtile_dir):
            os.mkdir(qtile_dir)
        elif os.path.isfile(qtile_dir):
            return # Just exist as an empty history
        self.filename = "{0}/{1}.hist".format(qtile_dir, name)
        print "Foobar: " + self.filename
        if not os.path.isfile(self.filename):
            return

        with open(self.filename) as hist_file:
            loaded_data = pickle.load(hist_file)
        if isinstance(loaded_data, list):
            print loaded_data
            self[:] = loaded_data

    def cleanup(self):
        try:
            with open(self.filename, "w") as hist_file:
                pickle.dump(list(self), hist_file)
        except IOError:
            return


class Prompt(base._TextBox):
    """
        A widget that prompts for user input. Input should be started using the
        .startInput method on this class.
    """
    completers = {
        "cmd": CommandCompleter,
        "group": GroupCompleter,
        None: NullCompleter
    }
    histories = {
        "cmd": PersistentHistory,
        "group": TransientHistory,
        None: TransientHistory,
        }
    defaults = manager.Defaults(
        ("font", "Arial", "Font"),
        ("fontsize", None, "Font pixel size. Calculated if None."),
        ("padding", None, "Padding. Calculated if None."),
        ("background", "000000", "Background colour"),
        ("foreground", "ffffff", "Foreground colour"),
        ("cursorblink", 0.5, "Cursor blink rate. 0 to disable.")
    )
    def __init__(self, name="prompt", **config):
        base._TextBox.__init__(self, "", bar.CALCULATED, **config)
        self.name = name
        self.active = False
        self.blink = False
        self.completer = None
        self.history = None
        self.userentered = 0

    def _configure(self, qtile, bar):
        base._TextBox._configure(self, qtile, bar)
        if self.cursorblink:
            self.timeout_add(self.cursorblink, self._blink)

    def startInput(self, prompt, callback, complete=None):
        """
            complete: Tab-completion. Can be None, or "cmd".

            Displays a prompt and starts to take one line of keyboard input
            from the user. When done, calls the callback with the input string
            as argument.
        """
        self.active = True
        self.prompt = prompt
        self.userInput = ""
        self.callback = callback
        self.completer = self.completers[complete](self.qtile)
        self.history = self.histories[complete](self.qtile, complete)
        self._update()
        self.bar.widget_grab_keyboard(self)

    def _blink(self):
        self.blink = not self.blink
        self._update()
        return True

    def _update(self):
        if self.active:
            self.text = "%s%s"%(self.prompt, self.userInput)
            if self.blink:
                self.text = self.text + "_"
            else:
                self.text = self.text + " "
        else:
            self.text = ""
        self.bar.draw()

    def handle_KeyPress(self, e):
        """
            KeyPress handler for the minibuffer.
            Currently only supports ASCII characters.
        """
        keysym = self.qtile.conn.keycode_to_keysym(e.detail, e.state)
        if keysym == xkeysyms.keysyms['Tab']:
            user_input = self.userInput[:self.userentered]
            self.userInput = self.completer.complete(user_input)
        elif keysym in self.history.keysyms:
            user_input = self.userInput[:self.userentered]
            hist = self.history.handleKeySym(keysym, user_input)
            if hist is not None:
                self.userInput = hist
        else:
            self.completer.reset()
            if keysym < 127 and chr(keysym) in string.printable:
                # No LookupString in XCB... oh, the shame! Unicode users beware!
                self.userInput += chr(keysym)
                self.userentered = len(self.userInput)
            elif keysym == xkeysyms.keysyms['BackSpace'] and len(self.userInput) > 0:
                self.userInput = self.userInput[:-1]
            elif keysym == xkeysyms.keysyms['Escape']:
                self.active = False
                self.history.cleanup()
                self.bar.widget_ungrab_keyboard()
            elif keysym == xkeysyms.keysyms['Return']:
                self.active = False
                self.history.insert(0, self.userInput)
                self.history.cleanup()
                self.bar.widget_ungrab_keyboard()
                self.callback(self.userInput)
        self._update()

    def cmd_fake_keypress(self, key):
        class Dummy:
            pass
        d = Dummy()
        keysym = xcbq.keysyms[key]
        d.detail = self.qtile.conn.keysym_to_keycode(keysym)
        d.state = 0
        self.handle_KeyPress(d)

    def cmd_info(self):
        """
            Returns a dictionary of info for this object.
        """
        return dict(
            name = self.name,
            width = self.width,
            text = self.text,
            active = self.active,
        )

