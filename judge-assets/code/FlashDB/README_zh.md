![](docs/_media/flashdb.png)

![GitHub Action](https://github.com/armink/FlashDB/workflows/AutoTestCI/badge.svg) [![license](https://img.shields.io/github/license/armink/FlashDB)](https://raw.githubusercontent.com/armink/FlashDB/master/LICENSE) [![docs](https://img.shields.io/badge/docs-perfect-blue)](http://armink.gitee.io/flashdb/#/zh-cn/ )

[EN](README.md) | 中文

> **说明**：本项目从 [armink/FlashDB](https://gitee.com/armink/FlashDB) fork 而来，用于练习高性能编程。已删除与 Linux 无关的平台代码（STM32、ESP32/8266、Zephyr 等嵌入式 demo 和移植文件），并增强了 Linux 平台的单元测试和性能基准测试。

## 简介

[FlashDB](http://armink.gitee.io/flashdb/#/zh-cn/) 是一款轻量级的 Flash 数据库，专注于提供 IoT 及嵌入式产品的数据存储方案。FlashDB 结合了 Flash 的特性，具有较强的性能及可靠性。并在保证极低的资源占用前提下，尽可能延长 Flash 使用寿命。

FlashDB 提供两种数据库模式：

- **键值数据库** ：是一种非关系数据库，它将数据存储为键值（Key-Value）对集合，其中键作为唯一标识符。KVDB 操作简洁，可扩展性强。
- **时序数据库** ：时间序列数据库 （Time Series Database , 简称 TSDB），它将数据按照 **时间顺序存储** 。TSDB 数据具有时间戳，数据存储量大，插入及查询性能高。

> 欢迎 Star&Fork ：https://gitee.com/armink/FlashDB

## 使用场景

FlashDB 提供了多样化的数据存储方案，不仅资源占用小，并且存储容量大，非常适合用于物联网产品。下面是主要应用场景：

- **键值数据库** ：
  - 产品参数存储
  - 用户配置信息存储
  - 小文件管理
- **时序数据库** ：
  - 存储动态产生的结构化数据：如 温湿度传感器采集的环境监测信息，智能手环实时记录的人体健康信息等
  - 记录运行日志：存储产品历史的运行日志，异常告警的记录等

## 主要特性

- 资源占用极低，内存占用几乎为 **0** ;
- 支持 多分区，**多实例** 。数据量大时，可细化分区，降低检索时间；
- 支持 **磨损平衡** ，延长 Flash 寿命；
- 支持 **掉电保护** 功能，可靠性高；
- 支持 字符串及 blob 两种 KV 类型，方便用户操作；
- 支持 KV **增量升级** ，产品固件升级后， KVDB 内容也支持自动升级；
- 支持 修改每条 TSDB 记录的状态，方便用户进行管理；
- 支持 POSIX 文件模式，适用于 Linux 等平台；

## 支持平台

| 平台   | 路径            | 存储类型     |
| ------ | --------------- | ------------ |
| linux  | `demos/linux`   | posix file   |

## 如何使用

FlashDB 提供了全面的文档说明，详见：http://armink.gitee.io/flashdb/#/zh-cn/ 

快速访问：

- [快速上手文档](http://armink.gitee.io/flashdb/#/zh-cn/quick-started)
- [移植文档](http://armink.gitee.io/flashdb/#/zh-cn/porting)
- [配置文档](http://armink.gitee.io/flashdb/#/zh-cn/configuration)
- [API 文档](http://armink.gitee.io/flashdb/#/zh-cn/api)

## 支持

如果你觉得 FlashDB 有用，欢迎支持原作者项目：https://gitee.com/armink/FlashDB

## 许可

采用 Apache-2.0 开源协议，细节请阅读项目中的 LICENSE 文件内容。
