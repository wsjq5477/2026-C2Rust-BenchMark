![](docs/_media/flashdb.png)

![GitHub Action](https://github.com/armink/FlashDB/workflows/AutoTestCI/badge.svg) [![license](https://img.shields.io/github/license/armink/FlashDB)](https://raw.githubusercontent.com/armink/FlashDB/master/LICENSE) [![docs](https://img.shields.io/badge/docs-perfect-blue)](https://armink.github.io/FlashDB/#/)

EN | [中文](README_zh.md)

> **Note**: This project is forked from [armink/FlashDB](https://gitee.com/armink/FlashDB) for practicing high-performance programming. Non-Linux platform code (STM32, ESP32/8266, Zephyr demos and ports) has been removed, and Linux unit tests and performance benchmarks have been added.

## Introduction

[FlashDB](https://github.com/armink/FlashDB) is a lightweight Flash database that focuses on providing data storage solutions for IoT and embedded products. Different from traditional database based on file system, [FlashDB](https://github.com/armink/FlashDB) combines the features of Flash and has strong performance and reliability. And under the premise of ensuring extremely low resource occupation, the service life of Flash should be extended as much as possible.

[FlashDB](https://github.com/armink/FlashDB) provides two database modes:

- **Key-value database**: It is a non-relational database that stores data as a collection of key-value pairs, where the key is used as a unique identifier. KVDB has simple operation and strong scalability.
- **Time Series Database**: Time Series Database (TSDB), which stores data in **time sequence**. TSDB data has a timestamp, a large amount of data storage, and high insertion and query performance.

## Usage scenario

FlashDB provides a variety of data storage solutions, not only has a small resource footprint, but also has a large storage capacity, which is very suitable for IoT products. The following are the main application scenarios:

- **Key-value database**:
  - Product parameter storage
  - User configuration information storage
  - Small file management
- **Time Series Database**: 
  - Store dynamically generated structured data: such as environmental monitoring information collected by temperature and humidity sensors, human health information recorded in real time by smart bracelets, etc.
  - Record operation log: store operation log of product history, record of abnormal alarm, etc.

## Key Features

- Very small footprint, ram usage is almost **0**;
- Support multiple partitions, **multiple instances**. When the amount of data is large, the partition can be refined to reduce the retrieval time;
- Support **wear balance** to extend Flash life;
- Support **Power-off protection** function, high reliability;
- Supports two KV types, string and blob, which is convenient for users to operate;
- Support KV **incremental upgrade**, after product firmware upgrade, KVDB content also supports automatic upgrade;
- Support to modify the status of each TSDB record to facilitate user management;
- Support POSIX file mode for Linux and other POSIX platforms;

## Supported platforms

| Platform | Path             | Storage Type |
| -------- | ---------------- | ------------ |
| linux    | `demos/linux`    | posix file   |

## How to use

FlashDB provides comprehensive documentation, see: https://armink.github.io/FlashDB/#/

Quick access:

- [Quick Start Document](http://armink.github.io/FlashDB/#/quick-started)
- [Porting Document](http://armink.github.io/FlashDB/#/porting)
- [Configuration Document](http://armink.github.io/FlashDB/#/configuration)
- [API Document](http://armink.github.io/FlashDB/#/api)

## License

The project uses the Apache-2.0 open source protocol. For details, please read the contents of the LICENSE file in the project.
