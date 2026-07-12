# IDC 自助查询插件

该插件面向 QQ 官方群机器人，实现固定指令解析、群与会员绑定、权限检查、
重复消息去重、IP 地址校验、查询网关调用及文本回复。固定查询不会进入大模型。

`scripts/one-click-deploy.sh` 会自动安装此插件。查询网关地址和服务令牌通过
`IDC_QUERY_API_BASE_URL`、`IDC_QUERY_API_TOKEN` 环境变量传给部署脚本，脚本会将其保存到
权限受限的 `docker/data/idc-query/config.env`，令牌不得提交到仓库或填写到插件公开配置中。

标准化接口约定见
[IDC 查询网关协议](https://github.com/csbsgyl/ai-lanbot/blob/main/docs/IDC_QUERY_GATEWAY.md)。
