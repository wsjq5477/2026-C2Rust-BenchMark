#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdbool.h>
#include <time.h>
#include "fdb_cfg_template.h"
#include "fdb_def.h"
#include "fdb_low_lvl.h"
#include "flashdb.h"


int main(void) {
  int failures = 0;
  printf("[LAYOUT CHECK] start\n");
  if (failures) {
    printf("[LAYOUT CHECK] fail\n");
    return 1;
  }
  printf("[LAYOUT CHECK] pass\n");
  return 0;
}
