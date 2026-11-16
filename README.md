# AI-LiNK 壁挂炉（Home Assistant 集成）

把 A.O. 史密斯 AI-LiNK 壁挂炉的热水循环接入 Home Assistant，按分钟控制，不再受官方 App 整点定时的限制。

已验证设备：**L1PB33-SA/S9**（云端 `productType` 为 24）。
实测结果：开启后壁挂炉点火、循环泵启动，关闭后回到待机。

## 功能

- `switch` 实体「热水循环」，可手动开关，也可用于自动化。
- 状态由设备上报的 `perWork`、`preWork`、`waterPumpSpeed` 判断，不依赖乐观假设。
- 传感器：出水温度、进水温度、生活热水设定温度、采暖设定温度、水流量、当前功率。
- 令牌自动续期：解析 JWT 过期时间，快过期时调用 `getLastToken` 换新令牌并写回配置项。
- 配置与选项全部在 UI 完成，不需要改 YAML。

## 安装

### 方式一：HACS（推荐）

1. 先把本仓库推送到你的 GitHub。仓库根目录应直接包含 `custom_components/`、`hacs.json` 和本文件。
2. 打开 HACS → 集成 → 右上角三个点 → 自定义存储库。
3. 填入仓库地址，类别选择「Integration」，点击添加。
4. 在 HACS 中搜索「AI-LiNK Boiler」，下载。
5. 重启 Home Assistant。
6. 设置 → 设备与服务 → 添加集成 → 搜索「AI-LiNK Boiler」。

### 方式二：手动安装

把 `custom_components/ailink_boiler` 整个目录复制到 HA 的 `/config/custom_components/`，重启后在「添加集成」里搜索「AI-LiNK Boiler」。

## 配置字段

提交表单时会实际调用一次云端接口校验，填错会当场提示。

| 字段 | 来源 | 是否必需 |
| --- | --- | --- |
| 用户 ID | 请求体里的 `userId` | 是 |
| 家庭 ID | 请求体里的 `familyId` | 是 |
| 设备 ID | 请求体里的 `deviceId` | 是 |
| 访问令牌 | 请求头 `authorization: Bearer` 后面那一串 | 是 |
| 手机号 | 请求体里的 `currUserMobile` | 否 |
| 轮询间隔 | 15 到 600 秒，默认 60 | 否 |

抓包方法：手机装 Surge 或 Reqable，开启抓包与 MITM，在 AI家智控 App 里操作一次热水循环，从 `ailink-api.hotwater.com.cn` 的请求里取上述参数。

## 实体

| 实体 | 说明 |
| --- | --- |
| `switch.<设备名>_re_shui_xun_huan` | 热水循环开关 |
| `sensor.<设备名>_chu_shui_wen_du` | 出水温度 |
| `sensor.<设备名>_jin_shui_wen_du` | 进水温度 |
| `sensor.<设备名>_sheng_huo_re_shui_she_ding_wen_du` | 生活热水设定温度 |
| `sensor.<设备名>_cai_nuan_she_ding_wen_du` | 采暖设定温度 |
| `sensor.<设备名>_shui_liu_liang` | 水流量，单位 L/min |
| `sensor.<设备名>_dang_qian_gong_lv` | 当前功率，单位 W |

实体 ID 以你 HA 里的实际值为准，可在「设置 → 实体」中搜索「热水循环」。

## 自动化示例

### 精确到分钟的固定时段

```yaml
alias: 热水循环-工作日晨间
triggers:
  - trigger: time
    at: "07:42:00"
conditions:
  - condition: state
    entity_id: binary_sensor.workday
    state: "on"
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.bi_gua_lu_re_shui_xun_huan
  - delay: "00:04:00"
  - action: switch.turn_off
    target:
      entity_id: switch.bi_gua_lu_re_shui_xun_huan
mode: single
```

### 进浴室按需触发

```yaml
alias: 热水循环-进浴室
triggers:
  - trigger: state
    entity_id: binary_sensor.bathroom_presence
    to: "on"
    for: "00:00:20"
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.bi_gua_lu_re_shui_xun_huan
  - delay: "00:03:00"
  - action: switch.turn_off
    target:
      entity_id: switch.bi_gua_lu_re_shui_xun_huan
mode: restart
```

### 蓝图

`blueprints/automation/ailink_boiler/cruise_on_presence.yaml` 是一个按需循环蓝图。把仓库里的 `blueprints` 目录复制到 `/config/blueprints/`，或从 GitHub 导入蓝图地址，然后在自动化里选择「AI-LiNK 壁挂炉按需热水循环」。

## 选项

在集成卡片上点「配置」：

- 修改轮询间隔。
- 粘贴新的访问令牌。留空表示保持当前令牌。
- 修改后会自动重载集成。

## 令牌续期

App 的访问令牌约 30 分钟过期。集成会在剩余有效期低于 120 秒时自动调用 `/AiLinkService/api/getLastToken` 换取新令牌，并写回配置项持久化。正常使用不需要每天重新抓包。

如果续期持续失败，通常是账号在别处退出了登录。重新在 App 登录并抓一个新令牌，在集成选项里更新即可。

## 故障排查

**添加集成时报「令牌无效或已过期」**
令牌本身已过期，重新抓包。注意不要带 `Bearer ` 前缀。

**报「该设备不是壁挂炉」**
云端 `productType` 不是 24。本集成目前只支持壁挂炉。

**实体显示不可用**
看 HA 日志里 `ailink_boiler` 的错误信息。常见原因是网络不通或令牌失效。

**开关状态延迟**
设备上报有 5 到 15 秒延迟。集成在下发指令后会在 8 秒和 20 秒各刷新一次，正常情况下最多滞后约 20 秒。

## 安全与免责

- 访问令牌等同账号登录凭据。不要提交到仓库、Issue 或公开渠道。
- 本项目为社区实现，与 A.O. 史密斯及其关联公司没有隶属关系。
- 云端接口可能随 App 版本变化。接口不可用时请提交 Issue，并附上脱敏后的状态码与错误消息。
- 零冷水频繁启停会增加燃气消耗和泵的磨损。建议在自动化里加「有人在家」和「距上次运行超过 20 分钟」的条件。

## 发布到 GitHub

仓库地址已按 `deyangchu/ailink-boiler-ha` 填好。推送命令：

```bash
git init
git add .
git commit -m "Initial version of AI-LiNK Boiler integration"
git branch -M main
git remote add origin git@github.com:deyangchu/ailink-boiler-ha.git
git push -u origin main
```

推送完成后，建议在 GitHub 上创建一个 `v0.1.0` 的 Release。HACS 没有 Release 也能安装，但有了 Release 版本号更清晰，后续更新也更可控。

然后把仓库地址加入 HACS 的自定义存储库即可。
