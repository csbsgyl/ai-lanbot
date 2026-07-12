# IDC 自助查询插件

该插件面向 QQ 官方群机器人，实现固定指令解析、群与会员绑定、权限检查、
重复消息去重、IP 地址校验、查询网关调用及文本回复。固定查询不会进入大模型。

`scripts/one-click-deploy.sh` 会自动安装此插件。部署后以管理员身份登录，在
**设置 > IDC 查询** 中配置网关地址、服务令牌、请求超时和 TLS 验证。设置接口只返回
令牌是否已配置，不会回传令牌原文；插件会在下一次查询时自动加载新配置，无需重启容器。

无人值守的首次部署仍可通过 `IDC_QUERY_API_BASE_URL`、`IDC_QUERY_API_TOKEN` 环境变量
预置配置。后台和部署脚本都会将配置保存到权限受限的
`docker/data/idc-query/config.env`。令牌不得提交到仓库或填写到插件公开配置中。

标准化接口约定见
[IDC 查询网关协议](https://github.com/csbsgyl/ai-lanbot/blob/main/docs/IDC_QUERY_GATEWAY.md)。
