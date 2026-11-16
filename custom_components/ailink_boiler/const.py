"""常量定义：接口地址、配置键、平台列表。"""

from homeassistant.const import Platform

DOMAIN = "ailink_boiler"

# 配置项
CONF_USER_ID = "user_id"
CONF_FAMILY_ID = "family_id"
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_MODEL = "device_model"
CONF_ACCESS_TOKEN = "access_token"
CONF_MOBILE = "mobile"
CONF_SCAN_INTERVAL = "scan_interval"

# 云端接口
API_BASE = "https://ailink-api.hotwater.com.cn"
PATH_DEVICE_INFO = "/AiLinkService/device/queryDeviceInfo"
PATH_DEVICE_STATUS = "/AiLinkService/appDevice/getDeviceCurrInfo"
PATH_INVOKE = "/AiLinkService/device/invokeMethod"
PATH_LAST_TOKEN = "/AiLinkService/api/getLastToken"

# 签名规则，来自 AI家智控 H5 的实际请求
ENCODE_SALT = "AILink_2021#"
SIGN_SECRET = "ng957stzh4zy3dts"

# 设备类别 24 表示壁挂炉
BOILER_PRODUCT_TYPE = "24"

# 轮询间隔（秒）
DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 15
MAX_SCAN_INTERVAL = 600

# 令牌剩余有效期低于该值时主动续期
TOKEN_REFRESH_MARGIN = 120
HTTP_TIMEOUT = 20

PLATFORMS = [Platform.SWITCH, Platform.SENSOR]
