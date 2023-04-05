# 此文件参考了 yjqiang/danmu 的工作
# https://github.com/yjqiang/danmu/blob/master/examples/huya/ws_huya_danmu_client.py

from enum import IntEnum
from .tars import tarscore

class WSUserInfo:
    def __init__(self):
        self.lUid = 0
        self.bAnonymous = True
        self.sGuid = ""
        self.sToken = ""
        self.lTid = 0
        self.lSid = 0
        self.lGroupId = 0
        self.lGroupType = 0

    def writeTo(self, t: tarscore.TarsOutputStream):
        t.write(tarscore.int64, 0, self.lUid)
        t.write(tarscore.boolean, 1, self.bAnonymous)
        t.write(tarscore.string, 2, self.sGuid)
        t.write(tarscore.string, 3, self.sToken)
        t.write(tarscore.int64, 4, self.lTid)
        t.write(tarscore.int64, 5, self.lSid)
        t.write(tarscore.int64, 6, self.lGroupId)
        t.write(tarscore.int64, 7, self.lGroupType)


class WebSocketCommand:
    def __init__(self):
        self.iCmdType = 0
        self.vData = b''

    def writeTo(self, t: tarscore.TarsOutputStream):
        t.write(tarscore.int32, 0, self.iCmdType),
        t.write(tarscore.bytes, 1, self.vData)

    def readFrom(self, t: tarscore.TarsInputStream):
        self.iCmdType = t.read(tarscore.int32, 0, False, self.iCmdType)
        self.vData = t.read(tarscore.bytes, 1, False, self.vData)


class UserHeartBeatReq:
    def __init__(self):
        self.tId = None
        self.lTid = 0
        self.lSid = 0
        self.lShortTid = 0
        self.lPid = 0
        self.bWatchVideo = True
        self.eLineType = EStreamLineType.STREAM_LINE_OLD_YY
        self.iFps = 0
        self.iAttendee = 0
        self.iBandwidth = 0
        self.iLastHeartElapseTime = 0

class WSPushMessage:
    def __init__(self):
        self.ePushType = 0,
        self.iUri = 0,
        self.sMsg = b''
        self.iProtocolType = 0

    def readFrom(self, t: tarscore.TarsInputStream):
        self.ePushType = t.read(tarscore.int32, 0, False, self.ePushType)
        self.iUri = t.read(tarscore.int64, 1, False, self.iUri)
        self.sMsg = t.read(tarscore.bytes, 2, False, self.sMsg)
        self.iProtocolType = t.read(tarscore.int32, 3, False, self.iProtocolType)

class WSPushMessage_V2:
    def __init__(self):
        self.sGroupId = b"",
        self.vMsgItem = []

    def readFrom(self, t: tarscore.TarsInputStream):
        self.sGroupId = t.read(tarscore.string, 0, False, self.sGroupId)
        self.vMsgItem = t.read(tarscore.vctclass(WSMsgItem), 1, False, self.vMsgItem)

class WSMsgItem(tarscore.struct):
    __tars_class__ = 'WSMsgItem'
    def __init__(self) -> None:
        self.iUri = 0,
        self.sMsg = b'',
        self.lMsgId = 0
    
    @staticmethod
    def readFrom(t: tarscore.TarsInputStream):
        var = WSMsgItem()
        var.iUri = t.read(tarscore.int64, 0, False, var.iUri)
        var.sMsg = t.read(tarscore.bytes, 1, False, var.sMsg)
        var.lMsgId = t.read(tarscore.int64, 2, False, var.lMsgId)
        return var

class SenderInfo(tarscore.struct):
    def __init__(self):
        self.lUid = 0
        self.lImid = 0
        self.sNickName = ""
        self.iGender = 0

    @staticmethod
    def readFrom(t: tarscore.TarsInputStream):
        var = SenderInfo()
        var.lUid = t.read(tarscore.int64, 0, False, var.lUid)
        var.lImid = t.read(tarscore.int64, 1, False, var.lImid)
        var.sNickName = t.read(tarscore.string, 2, False, var.sNickName)
        var.iGender = t.read(tarscore.int32, 3, False, var.iGender)
        return var

class ContentFormat(tarscore.struct):
    def __init__(self) -> None:
        self.iFontColor = 0
        self.iFontSize = 0
        self.iPopupStyle = 0
        self.iNickNameFontColor = 0
        self.iDarkFontColor = 0
        self.iDarkNickNameFontColor = 0

    @staticmethod
    def readFrom(t: tarscore.TarsInputStream):
        var = ContentFormat()
        var.iFontColor = t.read(tarscore.int32, 0, False, var.iFontColor)
        var.iFontSize = t.read(tarscore.int32, 1, False, var.iFontSize)
        var.iPopupStyle = t.read(tarscore.int32, 2, False, var.iPopupStyle)
        var.iNickNameFontColor = t.read(tarscore.int32, 3, False, var.iNickNameFontColor)
        var.iDarkFontColor = t.read(tarscore.int32, 4, False, var.iDarkFontColor)
        var.iDarkNickNameFontColor = t.read(tarscore.int32, 5, False, var.iDarkNickNameFontColor)
        return var
    
class BulletFormat(tarscore.struct):
    def __init__(self) -> None:
        self.iFontColor = 0
        self.iFontSize = 0
        self.iTextSpeed = 0
        self.iTransitionType = 0
        self.iPopupStyle = 0
        self.tBorderGroundFormat = None
        self.vGraduatedColor = None
        self.iAvatarFlag = 0
        self.iAvatarTerminalFlag = 0

    @staticmethod
    def readFrom(t: tarscore.TarsInputStream):
        var = BulletFormat()
        var.iFontColor = t.read(tarscore.int32, 0, False, var.iFontColor)
        var.iFontSize = t.read(tarscore.int32, 1, False, var.iFontSize)
        var.iTextSpeed = t.read(tarscore.int32, 2, False, var.iTextSpeed)
        var.iTransitionType = t.read(tarscore.int32, 3, False, var.iTransitionType)
        var.iPopupStyle = t.read(tarscore.int32, 4, False, var.iPopupStyle)
        # var.tBorderGroundFormat = t.readStruct(5, False, var.tBorderGroundFormat)
        # var.vGraduatedColor = t.readVector(6, False, var.vGraduatedColor)
        var.iAvatarFlag = t.read(tarscore.int32, 7, False, var.iAvatarFlag)
        var.iAvatarTerminalFlag = t.read(tarscore.int32, 8, False, var.iAvatarTerminalFlag)
        return var

class MessageNotice:
    def __init__(self):
        self.tUserInfo = None,
        self.lTid = 0,
        self.lSid = 0,
        self.sContent = "",
        self.iShowMode = 0,
        self.tFormat = None
        self.tBulletFormat = None
        self.iTermType = 0,
        self.vDecorationPrefix = None
        self.vDecorationSuffix = None
        self.vAtSomeone = None
        self.lPid = 0

    def readFrom(self, t: tarscore.TarsInputStream):
        self.tUserInfo = t.read(SenderInfo, 0, False, self.tUserInfo)
        self.lTid = t.read(tarscore.int64, 1, False, self.lTid)
        self.lSid = t.read(tarscore.int64, 2, False, self.lSid)
        self.sContent = t.read(tarscore.string, 3, False, self.sContent)
        self.iShowMode = t.read(tarscore.int32, 4, False, self.iShowMode)
        self.tFormat = t.read(ContentFormat, 5, False, self.tFormat)
        self.tBulletFormat = t.read(BulletFormat, 6, False, self.tBulletFormat)
        self.iTermType = t.read(tarscore.int32, 7, False, self.iTermType)
        # self.vDecorationPrefix = t.read(tarscore.vctclass, 8, False, self.vDecorationPrefix)
        # self.vDecorationSuffix = t.read(tarscore.vctclass, 9, False, self.vDecorationSuffix)
        # self.vAtSomeone = t.read(tarscore.vctclass, 10, False, self.vAtSomeone)
        self.lPid = t.read(tarscore.int64, 11, False, self.lPid)

class EWebSocketCommandType(IntEnum):
    EWSCmd_NULL = 0
    EWSCmd_RegisterReq = 1
    EWSCmd_RegisterRsp = 2
    EWSCmd_WupReq = 3
    EWSCmd_WupRsp = 4
    EWSCmdC2S_HeartBeat = 5
    EWSCmdS2C_HeartBeatAck = 6
    EWSCmdS2C_MsgPushReq = 7
    EWSCmdC2S_DeregisterReq = 8
    EWSCmdS2C_DeRegisterRsp = 9
    EWSCmdC2S_VerifyCookieReq = 10
    EWSCmdS2C_VerifyCookieRsp = 11
    EWSCmdC2S_VerifyHuyaTokenReq = 12
    EWSCmdS2C_VerifyHuyaTokenRsp = 13
    EWSCmdS2C_MsgPushReq_V2 = 22


class EStreamLineType(IntEnum):
    STREAM_LINE_OLD_YY = 0
    STREAM_LINE_WS = 1
    STREAM_LINE_NEW_YY = 2
    STREAM_LINE_AL = 3
    STREAM_LINE_HUYA = 4