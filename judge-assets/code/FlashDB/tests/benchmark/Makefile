CC = cc

ROOTPATH = ../..
INCDIR = -I. -I$(ROOTPATH)/inc
LIB = -lpthread

FDB_SRCS = $(ROOTPATH)/src/fdb.c \
           $(ROOTPATH)/src/fdb_file.c \
           $(ROOTPATH)/src/fdb_kvdb.c \
           $(ROOTPATH)/src/fdb_tsdb.c \
           $(ROOTPATH)/src/fdb_utils.c

FDB_OBJS = $(FDB_SRCS:.c=.o)

CFLAGS = -O2 -Wall -Wno-format

all: benchmark

benchmark: bench_main.o $(FDB_OBJS)
	$(CC) bench_main.o $(FDB_OBJS) -o benchmark $(LIB)

bench_main.o: bench_main.c fdb_cfg.h
	$(CC) $(CFLAGS) -c bench_main.c -o bench_main.o $(INCDIR)

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@ $(INCDIR)

bench: benchmark
	./benchmark

clean:
	rm -f benchmark bench_main.o $(FDB_OBJS)
	rm -rf bench_kvdb bench_tsdb

.PHONY: all bench clean
