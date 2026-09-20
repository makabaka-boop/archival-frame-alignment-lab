# 胶片扫描对应修复（Film-scan correspondence repair）

同一卷胶片被两台扫描机采集。掉帧与重复画面会让按首个相同指纹拼接的结果错序。
本服务在两条扫描数组之间求**全局最长对应**（最长公共子序列，LCS），并支持修复师用
**锚点集合**强制重算。纯后端 API：Python 3.12 + FastAPI + PostgreSQL，可重启续作。

## 对应关系的裁决规则

对应关系是零基索引对序列 `[[i, j], ...]`，满足：

- 两侧索引都**严格递增**；
- `left[i] == right[j]`，指纹按字节比较、**区分大小写、不做任何规范化**；
- 先**最大化对数**（LCS 长度）；
- 长度并列时，取索引对序列**字典序最小**者（逐对比较 `(i, j)`）；
- 没有任何匹配时返回 `[]`。

锚点（anchor）是一组必须全部出现在结果中的索引对：

- 锚点自身必须满足与对应关系相同的合法条件：成对、索引在界内、指纹相等，
  排序后两侧索引均严格递增（重复对、共 i、j 倒退、交叉均非法）；
- 结果必须包含**全部**锚点；锚点把问题切成互不相交的矩形间隙，每个间隙仍按
  「长度优先、字典序最小」独立求最优；
- 非法锚点返回 **422**，且数据库中的旧锚点与旧结果**保持不变**；
- 锚点集合是**整体替换**语义；提交空数组即清空锚点，恢复全局最优。

## 输入约束

- `left`、`right` 各为 JSON 字符串数组，长度 1～20000；
- 每个指纹为 1～32 个 **ASCII 可打印字符**（字节 0x20–0x7E）；
- 每个指纹值在每一侧至多出现 4 次；
- 最大输入在 3 秒内完成。核心算法利用「每值 ≤4 次」把匹配点限制在
  ≤ 4·n（80000）以内，用带代际标签的 Fenwick 树求后缀最优，
  整体复杂度 O(n + M log m)，M 为匹配点数。

## HTTP 协议

基准地址 `http://localhost:${API_PORT}`（容器内固定监听 8000）。

### `POST /api/projects`

提交两条扫描数组，立即计算并持久化全局最优。

请求：

```json
{ "left": ["a", "b", "a"], "right": ["b", "a", "b"] }
```

`201` 响应：

```json
{
  "id": 1,
  "left": ["a", "b", "a"],
  "right": ["b", "a", "b"],
  "anchors": [],
  "result": [[0, 1]],
  "length": 1
}
```

任何输入约束不满足返回 `422 {"detail": "..."}`。

### `GET /api/projects/{id}`

读取已保存的工程（数组、当前锚点、当前结果）。API 或数据库重启后数据仍在；
工程不存在返回 `404`。

### `PUT /api/projects/{id}/anchors`

**整体替换**锚点集合并立即重算。

```json
{ "anchors": [[1, 0]] }
```

- 合法：`200`，响应体同工程对象，`result` 包含全部锚点；
- 非法：`422`，原锚点与原结果不变（先在内存中完成校验与计算，通过后才写库）；
- `{"anchors": []}` 清空锚点并恢复全局最优；
- 锚点顺序可任意提交，服务会规范化为 `(i, j)` 升序存储。

### `GET /health`

存活探针，返回 `{"status": "ok"}`。

所有端点均为真实实现，没有假接口/桩接口。

## 运行（Docker Compose）

`compose.yaml` 通过 `API_PORT` 暴露服务（默认 8000）：

```bash
docker compose up --build            # 启动 db + api，http://localhost:8000
API_PORT=8080 docker compose up      # 改用宿主机 8080 端口
```

PostgreSQL 数据保存在命名卷 `pgdata` 中；API 容器以**非 root** 用户运行
（见 `Dockerfile`），重启后自动等待数据库就绪并继续使用已保存的工程。

## 验收（pytest 服务 `verify`）

验收测试只通过 HTTP 访问 API（黑盒），小规模用独立的 O(n·m) 穷举动态规划对账，
并覆盖重复指纹、首尾锚点、受约束的较短最优解、清空锚点恢复全局最优、非法锚点
422 且状态不变，以及 20000 项输入的 3 秒性能约束。

```bash
docker compose --profile verify run --rm verify
# 或在服务已启动后，对本地运行的 API 执行：
BASE_URL=http://localhost:8000 pytest -q
```

## 目录

```
app/solver.py    LCS / 锚点核心算法与锚点校验
app/db.py        PostgreSQL 连接池与持久化
app/main.py      FastAPI 路由、输入校验、422/404 语义
tests/           黑盒验收（穷举对账 + 性能 + 边界）
compose.yaml     db / api / verify 三服务
Dockerfile       多阶段；verify 目标带 pytest，全部阶段非 root
```
