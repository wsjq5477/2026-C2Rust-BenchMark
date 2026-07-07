# FlashDB：轻量级 Flash 数据库

[![license](https://img.shields.io/github/license/armink/FlashDB)](https://raw.githubusercontent.com/armink/FlashDB/master/LICENSE) [![docs](https://img.shields.io/badge/docs-perfect-blue)](http://armink.gitee.io/flashdb/#/zh-cn/ )

## 简介

[FlashDB](http://armink.gitee.io/flashdb/#/zh-cn/) 是一款轻量级的 Flash 数据库，专注于提供 IoT 及嵌入式产品的数据存储方案。FlashDB 结合了 Flash 的特性，具有较强的性能及可靠性。并在保证极低的资源占用前提下，尽可能延长 Flash 使用寿命。

FlashDB 提供两种数据库模式：

- **键值数据库** ：是一种非关系数据库，它将数据存储为键值（Key-Value）对集合，其中键作为唯一标识符。KVDB 操作简洁，可扩展性强。
- **时序数据库** ：时间序列数据库 （Time Series Database , 简称 TSDB），它将数据按照 **时间顺序存储** 。TSDB 数据具有时间戳，数据存储量大，插入及查询性能高。

> 欢迎 Star&Fork ：https://gitee.com/armink/FlashDB

## 主要特性

- 资源占用极低，内存占用几乎为 **0** ;
- 支持 多分区，**多实例** ；
- 支持 **磨损平衡** ，延长 Flash 寿命；
- 支持 **掉电保护** 功能，可靠性高；
- 支持 字符串及 blob 两种 KV 类型；
- 支持 KV **增量升级** ；
- 支持 POSIX 文件模式，适用于 Linux 等平台；

## 支持

 ![support](_media/wechat_support.png)

如果 FlashDB 解决了你的问题，不妨扫描上面二维码请我 **喝杯咖啡**~ 

## 许可

采用 Apache-2.0 开源协议，细节请阅读项目中的 LICENSE 文件内容。
