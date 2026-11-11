#!/usr/bin/env python3
"""Install opt-in CA IPC trace at actual XNU 8796 ownership boundaries."""
import argparse
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = '#include <kern/NabuCaIpcTrace.h>\n'


def replace(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f'Expected one CA IPC source anchor, got {text.count(old)}: {old[:100]!r}')
    return text.replace(old, new, 1)


def alter_function(text, start, next_start, transform):
    begin = text.index(start)
    end = text.index(next_start, begin)
    return text[:begin] + transform(text[begin:end]) + text[end:]


def patch_mach_msg(text):
    def send(s):
        s = replace(s, '\t/* holding kmsg ref */', '''\t/* Trace the validated, copied simple body before copyin can consume rights. */
\tNabuCaIpcSnapshot ca_trace = nabu_ca_ipc_capture(kmsg, task_pid(current_task()));
\tnabu_ca_ipc_begin(&ca_trace, NabuCaIpcSendBegin);
\tnabu_ca_ipc_paired(&ca_trace, NabuCaIpcSendPayload, ca_trace.inputTimeBits, option64, msg_timeout);

\t/* holding kmsg ref */''')
        s = replace(s, '''\tif (mr != MACH_MSG_SUCCESS) {
\t\tipc_kmsg_free(kmsg);
\t\treturn mr;
\t}''', '''\tif (mr != MACH_MSG_SUCCESS) {
\t\tnabu_ca_ipc_paired(&ca_trace, NabuCaIpcSendResult, ca_trace.cookie, (uint32_t)mr, 1);
\t\tipc_kmsg_free(kmsg);
\t\tnabu_ca_ipc_paired(&ca_trace, NabuCaIpcSendReturn, ca_trace.cookie, (uint32_t)mr, 0);
\t\treturn mr;
\t}''')
        s = replace(s, '\tmr = ipc_kmsg_send(kmsg, option64, msg_timeout);', '''\tmr = ipc_kmsg_send(kmsg, option64, msg_timeout);
\t/* Success transfers ownership. Only the stack snapshot is valid here. */
\tnabu_ca_ipc_paired(&ca_trace, NabuCaIpcSendResult, ca_trace.cookie, (uint32_t)mr, 2);''')
        s = replace(s, '\n\treturn mr;\n}', '''
\tnabu_ca_ipc_paired(&ca_trace, NabuCaIpcSendReturn, ca_trace.cookie, (uint32_t)mr, 0);
\treturn mr;
}''')
        return s
    text = alter_function(text, 'mach_msg_trap_send(\n', '/*\n *  Routine:    mach_msg_trap_receive', send)
    def receive(s):
        s = replace(s, '\tmach_msg_size_t   cpout_msg_size = 0, cpout_aux_size = 0;', '''\tmach_msg_size_t   cpout_msg_size = 0, cpout_aux_size = 0;
\tNabuCaIpcSnapshot ca_trace = {0};
\t/* LARGE/timeout paths may not own a message at all. */
\tif (mr == MACH_MSG_SUCCESS ||
\t    (mr == MACH_RCV_TOO_LARGE && !(option64 & MACH64_RCV_LARGE))) {
\t\tca_trace = nabu_ca_ipc_capture(kmsg, -1);
\t\tnabu_ca_ipc_begin(&ca_trace, NabuCaIpcReceiveBegin);
\t\tnabu_ca_ipc_paired(&ca_trace, NabuCaIpcReceivePayload, ca_trace.inputTimeBits,
\t\t    nabu_ca_ipc_pair((uint32_t)task_pid(current_task()), seqno), (uint32_t)mr);
\t}''')
        s = replace(s, '\t\treturn mr;', '''\t\tnabu_ca_ipc_paired(&ca_trace, NabuCaIpcReceiveResult, ca_trace.cookie, (uint32_t)mr,
\t\t    nabu_ca_ipc_pair(cpout_aux_size, cpout_msg_size));
\t\treturn mr;''')
        s = replace(s, '\n\treturn mr;\n}', '''
\t/* copyout/put have consumed the kmsg; no pointer is dereferenced here. */
\tnabu_ca_ipc_paired(&ca_trace, NabuCaIpcReceiveResult, ca_trace.cookie, (uint32_t)mr,
\t    nabu_ca_ipc_pair(cpout_aux_size, cpout_msg_size));
\treturn mr;
}''')
        return s
    return alter_function(text, 'mach_msg_receive_results_kevent(\n', '\nmach_msg_return_t\nmach_msg_receive_results(void)', receive)


def patch_mqueue(text):
    def post(s):
        s = replace(s, '\tboolean_t destroy_msg = FALSE;', '''\tboolean_t destroy_msg = FALSE;
\tconst NabuCaIpcSnapshot ca_trace = nabu_ca_ipc_capture(kmsg, -1);''')
        s = replace(s, '''\t\t\t} else if (!ipc_kmsg_enqueue_qos(&mqueue->imq_messages, kmsg)) {
\t\t\t\t/*
\t\t\t\t * queue was not empty and qos
\t\t\t\t * didn't change, nothing to do.
\t\t\t\t */
\t\t\t} else if (ip_in_a_space(port) &&
\t\t\t    is_active(ip_get_receiver(port)) &&
\t\t\t    ipc_port_has_klist(port)) {
\t\t\t\t/*
\t\t\t\t * queue was empty or qos changed
\t\t\t\t * we need to tell kqueue, unless
\t\t\t\t * the space is getting torn down
\t\t\t\t */
\t\t\t\tKNOTE(&port->ip_klist, 0);
\t\t\t}''', '''\t\t\t} else {
\t\t\t\tbool changed = ipc_kmsg_enqueue_qos(&mqueue->imq_messages, kmsg);
\t\t\t\tnabu_ca_ipc_stage(&ca_trace, NabuCaIpcQueued,
\t\t\t\t    nabu_ca_ipc_pair(mqueue->imq_msgcount, mqueue->imq_seqno));
\t\t\t\tif (changed && ip_in_a_space(port) &&
\t\t\t\t    is_active(ip_get_receiver(port)) && ipc_port_has_klist(port)) {
\t\t\t\t\tKNOTE(&port->ip_klist, 0);
\t\t\t\t}
\t\t\t}''')
        s = replace(s, '''\t\t\tipc_kmsg_enqueue_qos(&mqueue->imq_messages, kmsg);
\t\t\tipc_mqueue_peek_on_thread_locked''', '''\t\t\tipc_kmsg_enqueue_qos(&mqueue->imq_messages, kmsg);
\t\t\tnabu_ca_ipc_stage(&ca_trace, NabuCaIpcQueued,
\t\t\t    nabu_ca_ipc_pair(mqueue->imq_msgcount, mqueue->imq_seqno));
\t\t\tipc_mqueue_peek_on_thread_locked''')
        s = replace(s, '\t\t\treceiver->ith_seqno = mqueue->imq_seqno++;', '''\t\t\treceiver->ith_seqno = mqueue->imq_seqno++;
\t\t\tnabu_ca_ipc_stage(&ca_trace, NabuCaIpcDirect,
\t\t\t    nabu_ca_ipc_pair((uint32_t)task_pid(get_threadtask(receiver)), receiver->ith_seqno));''')
        s = replace(s, '\t\treceiver->ith_receiver_name = mqueue->imq_receiver_name;', '''\t\tnabu_ca_ipc_stage(&ca_trace, NabuCaIpcReceiveNotTaken,
\t\t    nabu_ca_ipc_pair((uint32_t)task_pid(get_threadtask(receiver)), MACH_RCV_TOO_LARGE));
\t\treceiver->ith_receiver_name = mqueue->imq_receiver_name;''')
        s = replace(s, '\tif (destroy_msg) {\n\t\tipc_kmsg_destroy', '''\tif (destroy_msg) {
\t\tnabu_ca_ipc_drop(&ca_trace, NabuCaIpcPostDestroyed, MACH_SEND_INVALID_DEST);
\t\tipc_kmsg_destroy''')
        return s
    # Skip its forward declaration by selecting the static definition with body.
    text = alter_function(text, 'static void\nipc_mqueue_post(\n', '\n\nstatic void\nipc_mqueue_receive_results', post)
    def select(s):
        s = replace(s, '\tassert(kmsg != IKM_NULL);', '''\tassert(kmsg != IKM_NULL);
\tconst NabuCaIpcSnapshot ca_trace = nabu_ca_ipc_capture(kmsg, -1);''')
        s = replace(s, '\t\t\tthread->ith_state = mr;\n\t\t\treturn;', '''\t\t\tthread->ith_state = mr;
\t\t\tnabu_ca_ipc_stage(&ca_trace, NabuCaIpcReceiveNotTaken,
\t\t\t    nabu_ca_ipc_pair((uint32_t)task_pid(get_threadtask(thread)), (uint32_t)mr));
\t\t\treturn;''')
        s = replace(s, '\n\tthread->ith_state = mr;', '''
\tthread->ith_state = mr;
\tnabu_ca_ipc_stage(&ca_trace, NabuCaIpcDequeued,
\t    nabu_ca_ipc_pair((uint32_t)task_pid(get_threadtask(thread)), thread->ith_seqno));''')
        return s
    return alter_function(text, 'void\nipc_mqueue_select_on_thread_locked(\n', '\n/*\n *\tRoutine:\tipc_mqueue_peek_locked', select)


def patch_kmsg(text):
    # Perform the repeated-tail edits separately to preserve their order.
    def fixed_send(s):
        s = replace(s, '\n\thdr = ikm_header(kmsg);', '\n\thdr = ikm_header(kmsg);\n\tconst NabuCaIpcSnapshot ca_trace = nabu_ca_ipc_capture(kmsg, -1);')
        s = replace(s, '\tif (hdr->msgh_bits & MACH_MSGH_BITS_CIRCULAR) {', '\tif (hdr->msgh_bits & MACH_MSGH_BITS_CIRCULAR) {\n\t\tnabu_ca_ipc_drop(&ca_trace, NabuCaIpcCircular, MACH_MSGH_BITS_CIRCULAR);')
        anchor = '\t\tipc_kmsg_destroy(kmsg, IPC_KMSG_DESTROY_SKIP_REMOTE);\n\t\tKDBG(MACHDBG_CODE(DBG_MACH_IPC, MACH_IPC_KMSG_INFO) | DBG_FUNC_END, MACH_SEND_INVALID_DEST);'
        chunks = s.split(anchor)
        if len(chunks) != 3: raise RuntimeError('Expected two inactive-port destruction sites')
        return (chunks[0] + '\t\tnabu_ca_ipc_drop(&ca_trace, NabuCaIpcInactivePort, MACH_SEND_INVALID_DEST);\n' + anchor +
                chunks[1] + '\t\tnabu_ca_ipc_drop(&ca_trace, NabuCaIpcPortDiedWhileSending, MACH_SEND_INVALID_DEST);\n' + anchor + chunks[2])
    return alter_function(text, 'ipc_kmsg_send(\n', '\n/*\n *', fixed_send)


TRANSFORMS = {'mach_msg.c': patch_mach_msg, 'ipc_mqueue.c': patch_mqueue, 'ipc_kmsg.c': patch_kmsg}


def install(tree):
    tree = Path(tree)
    result = {}
    for name, transform in TRANSFORMS.items():
        path = tree / 'osfmk/ipc' / name
        text = path.read_text(encoding='utf-8')
        if INCLUDE not in text:
            text = transform(text)
            text = replace(text, '#include <ipc/ipc_kmsg.h>\n', '#include <ipc/ipc_kmsg.h>\n' + INCLUDE)
            path.write_text(text, encoding='utf-8')
        result[name] = str(path)
    target = tree / 'osfmk/kern/NabuCaIpcTrace.h'
    shutil.copyfile(ROOT / 'patches/nabu-diagnostics/NabuCaIpcTrace.h', target)
    return {'files': result, 'header': str(target), 'events': [64, 75],
            'default_enabled': False, 'wire_message_changes': False,
            'bridge_required': ['nabu_ca_ipc_trace_window', 'nabu_ca_ipc_trace_record']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tree', type=Path, required=True)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    result = install(a.tree)
    encoded = json.dumps(result, indent=2) + '\n'
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(encoded, encoding='utf-8')
    print(encoded, end='')


if __name__ == '__main__':
    main()
