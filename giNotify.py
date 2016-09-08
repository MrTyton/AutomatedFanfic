from gi import require_version as gir

gir('Notify', '0.7')

from gi.repository import GObject
from gi.repository import Notify
import sys
from os.path import join, dirname, abspath

class Notification(GObject.Object):
    def __init__(self):

        super(Notification, self).__init__()
        # lets initialise with the application name
        Notify.init("Fanfiction")
        self.icon = join(dirname(abspath(__file__)), 'ff.png')

    def send_notification(self, title, text):

        n = Notify.Notification.new(title, text, self.icon)
        n.show()
