#!/usr/bin/env python3
"""Replay the actual patched QMI registration/event bodies on the host."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def function(text, name):
    start = re.search(r'static\s+(?:int|void)\s+' + name + r'\(', text).start()
    opening = text.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


PRELUDE = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
struct qmi_response_type_v01 { u16 result, error; };
struct qmi_elem_info { int unused; };
struct qmi_txn { void *response; };
struct qmi_handle { int unused; };
struct list_head { struct list_head *next, *prev; };
struct work_struct { int unused; };
struct ath10k_snoc { bool xo_cal_supported; unsigned long flags; };
struct ath10k { struct ath10k_snoc snoc; };
struct ath10k_qmi {
  struct ath10k *ar;
  struct qmi_handle qmi_hdl;
  bool fw_ready, no_msa_ready_indicator;
  int event_lock;
  struct list_head event_list;
  struct work_struct event_work;
};
enum {
  ATH10K_QMI_EVENT_SERVER_ARRIVE,
  ATH10K_QMI_EVENT_SERVER_EXIT,
  ATH10K_QMI_EVENT_FW_READY_IND,
  ATH10K_QMI_EVENT_FW_DOWN_IND,
  ATH10K_QMI_EVENT_MSA_READY_IND
};
struct ath10k_qmi_driver_event { struct list_head list; int type; };
#define container_of(ptr, type, member) ((type *)((char *)(ptr) - offsetof(type, member)))
#define ath10k_snoc_priv(ar) (&(ar)->snoc)
#define ath10k_err(...) ((void)0)
#define ath10k_dbg(...) ((void)0)
#define ath10k_info(...) ((void)0)
#define ath10k_warn(...) ((void)0)
#define ATH10K_DBG_QMI 0
#define ATH10K_SNOC_FLAG_UNREGISTERING 0
#define ATH10K_SNOC_FLAG_MODEM_STOPPED 1
#define test_bit(bit, flags) ((*(flags) >> (bit)) & 1)
#define QMI_RESULT_SUCCESS_V01 0
#define HZ 1000
#define spin_lock(x) ((void)0)
#define spin_unlock(x) ((void)0)
#define list_empty(head) ((head)->next == (head))
#define list_first_entry(head, type, member) container_of((head)->next, type, member)
static void list_del(struct list_head *node) {
  node->prev->next = node->next;
  node->next->prev = node->prev;
}
#define kfree free
static int initialized, sent, waited, canceled, capped, notified, forbidden;
static int init_error, send_error, wait_error, cap_error;
static int last_event;
'''

TRANSPORT = r'''
static struct wlfw_ind_register_resp_msg_v01 reply;
static struct wlfw_ind_register_req_msg_v01 request;
const struct qmi_elem_info wlfw_ind_register_req_msg_v01_ei[1] = {{0}};
const struct qmi_elem_info wlfw_ind_register_resp_msg_v01_ei[1] = {{0}};
static int qmi_txn_init(struct qmi_handle *h, struct qmi_txn *t,
                        const struct qmi_elem_info *ei, void *out) {
  (void)h; (void)ei; ++initialized; t->response = out; return init_error;
}
static int qmi_send_request(struct qmi_handle *h, void *sq, struct qmi_txn *t,
                            unsigned id, unsigned size,
                            const struct qmi_elem_info *ei, const void *req) {
  (void)h; (void)sq; (void)t; (void)ei;
  assert(id == 0x20); assert(size == 50);
  request = *(const struct wlfw_ind_register_req_msg_v01 *)req;
  assert(request.client_id_valid && request.client_id == 0x4b4e454c);
  assert(request.fw_ready_enable_valid && request.fw_ready_enable);
  assert(request.msa_ready_enable_valid && !request.msa_ready_enable);
  ++sent; return send_error;
}
static int qmi_txn_wait(struct qmi_txn *t, unsigned timeout) {
  assert(timeout); ++waited;
  *(struct wlfw_ind_register_resp_msg_v01 *)t->response = reply;
  return wait_error;
}
static void qmi_txn_cancel(struct qmi_txn *t) { (void)t; ++canceled; }
static int ath10k_qmi_cap_send_sync_msg(struct ath10k_qmi *q) {
  assert(q->fw_ready); ++capped; return cap_error;
}
static void ath10k_snoc_fw_indication(struct ath10k *a, int type) {
  (void)a; ++notified; last_event = type;
}
#define FORBIDDEN(name) static int name(struct ath10k_qmi *q) { (void)q; ++forbidden; return 0; }
FORBIDDEN(ath10k_qmi_host_cap_send_sync)
FORBIDDEN(ath10k_qmi_msa_mem_info_send_sync_msg)
FORBIDDEN(ath10k_qmi_setup_msa_permissions)
FORBIDDEN(ath10k_qmi_msa_ready_send_sync_msg)
FORBIDDEN(ath10k_qmi_fetch_board_file)
FORBIDDEN(ath10k_qmi_bdf_dnld_send_sync)
FORBIDDEN(ath10k_qmi_send_cal_report_req)
FORBIDDEN(ath10k_qmi_remove_msa_permission)
static void ath10k_core_free_board_files(struct ath10k *a) { (void)a; }
static void ath10k_snoc_fw_crashed_dump(struct ath10k *a) { (void)a; }
static void msleep(unsigned ms) { (void)ms; }
'''

TEST = r'''
static void reset(struct ath10k_qmi *q) {
  initialized = sent = waited = canceled = capped = notified = forbidden = 0;
  init_error = send_error = wait_error = cap_error = 0;
  last_event = -1;
  reply = (struct wlfw_ind_register_resp_msg_v01){0};
  request = (struct wlfw_ind_register_req_msg_v01){0};
  q->fw_ready = false;
  q->event_list.next = q->event_list.prev = &q->event_list;
}
static void event(struct ath10k_qmi *q, int type) {
  struct ath10k_qmi_driver_event *e = calloc(1, sizeof(*e));
  assert(e); e->type = type;
  e->list.next = &q->event_list; e->list.prev = q->event_list.prev;
  q->event_list.prev->next = &e->list; q->event_list.prev = &e->list;
  ath10k_qmi_driver_event_work(&q->event_work);
  assert(list_empty(&q->event_list)); assert(forbidden == 0);
}
int main(void) {
  struct ath10k ar = {0};
  struct ath10k_qmi q = {.ar = &ar};
  unsigned cases = 0;
  for (int no_msa = 0; no_msa <= 1; ++no_msa) {
    q.no_msa_ready_indicator = no_msa;
    for (int scenario = 0; scenario < 11; ++scenario) {
      reset(&q);
      reply.fw_status_valid = 1;
      reply.fw_status = QMI_WLFW_FW_READY_V01;
      switch (scenario) {
      case 0: init_error = -ENOMEM; break;
      case 1: send_error = -EIO; break;
      case 2: wait_error = -ETIMEDOUT; break;
      case 3: reply.resp.result = 1; reply.resp.error = 7; break;
      case 4: reply.fw_status_valid = 0; break;
      case 5: reply.fw_status = 0; break;
      case 6: reply.fw_status = 1; break;
      case 7: q.fw_ready = true; reply.fw_status_valid = 0; break;
      case 8: cap_error = -EIO; break;
      case 9: break;
      case 10: ar.snoc.xo_cal_supported = true; break;
      }
      /* Neither early indication may begin the backend or fetch board data. */
      event(&q, ATH10K_QMI_EVENT_FW_READY_IND);
      event(&q, ATH10K_QMI_EVENT_MSA_READY_IND);
      assert(notified == 0 && sent == 0 && capped == 0);
      event(&q, ATH10K_QMI_EVENT_SERVER_ARRIVE);
      assert(initialized == 1);
      assert(sent == (scenario != 0));
      assert(waited == (scenario > 1));
      assert(canceled == (scenario == 1));
      assert(q.fw_ready == (scenario >= 8));
      assert(capped == (scenario >= 8));
      assert(notified == (scenario >= 9));
      if (scenario >= 9) assert(last_event == ATH10K_QMI_EVENT_FW_READY_IND);
      if (scenario == 10) assert(request.xo_cal_enable_valid && request.xo_cal_enable);
      /* Late duplicate indications must not publish ready a second time. */
      event(&q, ATH10K_QMI_EVENT_FW_READY_IND);
      event(&q, ATH10K_QMI_EVENT_MSA_READY_IND);
      assert(notified == (scenario >= 9));
      event(&q, ATH10K_QMI_EVENT_SERVER_EXIT);
      assert(last_event == ATH10K_QMI_EVENT_FW_DOWN_IND);
      ++cases;
    }
  }
  printf("{\"status\":\"passed\",\"scenarios\":%u,\"bootstrap_calls\":0}\n", cases);
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'build/nabu-ath10k/ready-only-v128/linux/ath10k/qmi.c')
    parser.add_argument('--output', type=Path, default=ROOT / 'log/host/wireless-v128/ath10k-handoff')
    parser.add_argument('--compiler', default='clang' if sys.platform == 'darwin' else 'clang-18')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = args.source.read_text()
    header = args.source.with_name('qmi_wlfw_v01.h').read_text()
    names = ('ath10k_qmi_ind_register_send_sync_msg', 'ath10k_qmi_event_server_arrive',
             'ath10k_qmi_event_server_exit', 'ath10k_qmi_event_msa_ready',
             'ath10k_qmi_event_fw_ready_ind', 'ath10k_qmi_driver_event_work')
    definitions = []
    for name in ('ATH10K_QMI_CLIENT_ID', 'ATH10K_QMI_TIMEOUT', 'QMI_WLFW_IND_REGISTER_REQ_V01',
                 'QMI_WLFW_FW_READY_V01', 'WLFW_IND_REGISTER_REQ_MSG_V01_MAX_MSG_LEN'):
        definitions.append(re.search(r'^#define\s+' + name + r'\s+[^\n]+', source + '\n' + header, re.M)[0])
    for name in ('wlfw_ind_register_req_msg_v01', 'wlfw_ind_register_resp_msg_v01'):
        definitions.append(re.search(r'struct ' + name + r' \{.*?\n\};', header, re.S)[0])
    generated = args.output / 'handoff.c'
    generated.write_text('\n'.join([PRELUDE, *definitions, TRANSPORT,
                                    *[function(source, n) for n in names], TEST]))
    executable = args.output / 'handoff'
    command = [args.compiler, '-std=gnu17', '-O1', '-g', '-fsanitize=address,undefined',
               '-fno-sanitize-recover=all', str(generated), '-o', str(executable)]
    subprocess.run(command, check=True)
    result = subprocess.run([str(executable)], text=True, capture_output=True, check=True)
    report = json.loads(result.stdout)
    report.update(source=str(args.source), actual_functions=list(names), compiler=args.compiler,
                  sanitizer='address,undefined', limitations='Host control-flow replay; no QMI wire codec or hardware emulation')
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
