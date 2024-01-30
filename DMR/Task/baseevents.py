
class BaseEvents():
    def __init__(self, name, config):
        self.name = name
        self.config = config

    def onReady(self):
        pass

    def onLiveStart(self):
        pass

    def onLiveStreamEnd(self):
        pass

    def onLiveEnd(self):
        pass

    def onLiveStop(self):
        pass

    def onLiveSegment(self):
        pass

    def onLiveError(self):
        pass

    def onRenderStart(self):
        pass

    def onRenderEnd(self):
        pass

    def onRenderStop(self):
        pass

    def onRenderError(self):
        pass

    def onUploadStart(self):
        pass

    def onUploadEnd(self):
        pass

    def onUploadStop(self):
        pass

    def onUploadError(self):
        pass

    def onCleanStart(self):
        pass

    def onCleanEnd(self):
        pass

    def onCleanStop(self):
        pass

    def onCleanError(self):
        pass

    def onExit(self):
        pass

    
