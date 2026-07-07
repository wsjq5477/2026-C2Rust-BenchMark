# FlashDB: A lightweight Flash database for IoT and embedded products

[![license](https://img.shields.io/github/license/armink/FlashDB)](https://raw.githubusercontent.com/armink/FlashDB/master/LICENSE) 

## Introduction

[FlashDB](https://github.com/armink/FlashDB) is a lightweight Flash database that focuses on providing data storage solutions for IoT and embedded products. [FlashDB](https://github.com/armink/FlashDB) combines the features of Flash and has strong performance and reliability. And under the premise of ensuring extremely low resource occupation, the service life of Flash should be extended as much as possible.

FlashDB provides two database modes:

- **Key-value database**: It is a non-relational database that stores data as a collection of key-value pairs, where the key is used as a unique identifier. KVDB has simple operation and strong scalability.
- **Time Series Database**: Time Series Database (TSDB), which stores data in **time sequence**. TSDB data has a timestamp, a large amount of data storage, and high insertion and query performance.

## Key Features

- Very small footprint, ram usage is almost **0**;
- Support multiple partitions, **multiple instances**;
- Support **wear balance** to extend Flash life;
- Support **Power-off protection** function, high reliability;
- Supports two KV types, string and blob;
- Support KV **incremental upgrade**;
- Support POSIX file mode for Linux and other POSIX platforms;

## License

The project uses the Apache-2.0 open source protocol. For details, please read the contents of the LICENSE file in the project.
