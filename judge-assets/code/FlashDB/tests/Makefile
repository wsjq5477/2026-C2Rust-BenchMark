CC = cc

ROOTPATH=..
INCDIR = -I. -I$(ROOTPATH)/inc
LIB = -lpthread

FDB_SRCS = $(ROOTPATH)/src/fdb.c \
           $(ROOTPATH)/src/fdb_file.c \
           $(ROOTPATH)/src/fdb_kvdb.c \
           $(ROOTPATH)/src/fdb_tsdb.c \
           $(ROOTPATH)/src/fdb_utils.c

FDB_OBJS = $(FDB_SRCS:.c=.o)

CFLAGS = -O0 -g3 -Wall -Wno-format

all: kvdb_test tsdb_test

kvdb_test: kvdb_main.o $(FDB_OBJS)
	$(CC) kvdb_main.o $(FDB_OBJS) -o kvdb_test $(LIB)

tsdb_test: tsdb_main.o $(FDB_OBJS)
	$(CC) tsdb_main.o $(FDB_OBJS) -o tsdb_test $(LIB)

kvdb_main.o: kvdb_main.c fdb_kvdb_tc.c test_helpers.h
	$(CC) $(CFLAGS) -c kvdb_main.c -o kvdb_main.o $(INCDIR)

tsdb_main.o: tsdb_main.c fdb_tsdb_tc.c test_helpers.h
	$(CC) $(CFLAGS) -c tsdb_main.c -o tsdb_main.o $(INCDIR)

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@ $(INCDIR)

test: kvdb_test tsdb_test
	@echo "=== Running KVDB Test ==="
	./kvdb_test
	@echo ""
	@echo "=== Running TSDB Test ==="
	./tsdb_test

kvdb_run: kvdb_test
	./kvdb_test

tsdb_run: tsdb_test
	./tsdb_test

clean:
	rm -f kvdb_test tsdb_test kvdb_main.o tsdb_main.o main.o $(FDB_OBJS)
	rm -rf fdb_kvdb1 fdb_tsdb1 storage_tsdb

.PHONY: all test kvdb_run tsdb_run clean
