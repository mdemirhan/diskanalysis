#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdlib.h>
#include <string.h>

/*
 * Prefix trie for O(m) startswith matching against multiple prefixes.
 *
 * Declares GIL-free safety (Py_MOD_GIL_NOT_USED) for free-threaded Python.
 * The trie is built once (add_prefix + build) then only read during iter()
 * — inherently thread-safe for concurrent readers.
 *
 * Python API:
 *   pt = PrefixTrie()
 *   pt.add_prefix(key: str, value: object)
 *   pt.build()
 *   pt.iter(text: str) -> list[object]
 */

/* Full byte range: 256 children per node (1 KB each).  This trades memory
 * for speed — constant-time transitions in the hot loop.  Acceptable because
 * prefixes are short, so the trie has few nodes. */
#define PT_ALPHA 256

typedef struct {
    int children[PT_ALPHA];
    int output;       /* index into values[], -1 = none */
} PTNode;

typedef struct {
    PyObject_HEAD
    PTNode *nodes;
    int n_nodes;
    int cap_nodes;
    PyObject **values;
    int n_values;
    int cap_values;
    int built;        /* 1 after build() */
} PrefixTrieObject;

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

static int
pt_new_node(PrefixTrieObject *self)
{
    if (self->n_nodes >= self->cap_nodes) {
        int new_cap = self->cap_nodes * 2;
        PTNode *tmp = (PTNode *)realloc(self->nodes,
                                        sizeof(PTNode) * (size_t)new_cap);
        if (!tmp) return -1;
        self->nodes = tmp;
        self->cap_nodes = new_cap;
    }
    PTNode *nd = &self->nodes[self->n_nodes];
    /* 0xFF bytes → -1 in two's complement for 32-bit ints (all modern platforms). */
    memset(nd->children, 0xff, sizeof(nd->children));
    nd->output = -1;
    return self->n_nodes++;
}

static int
pt_new_value(PrefixTrieObject *self, PyObject *val)
{
    if (self->n_values >= self->cap_values) {
        int new_cap = self->cap_values * 2;
        PyObject **tv = (PyObject **)realloc(
            self->values, sizeof(PyObject *) * (size_t)new_cap);
        if (!tv) return -1;
        self->values = tv;
        self->cap_values = new_cap;
    }
    Py_INCREF(val);
    self->values[self->n_values] = val;
    return self->n_values++;
}

/* ------------------------------------------------------------------ */
/* Type methods                                                       */
/* ------------------------------------------------------------------ */

static PyObject *
PrefixTrie_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    (void)args; (void)kwds;
    PrefixTrieObject *self = (PrefixTrieObject *)type->tp_alloc(type, 0);
    if (!self) return NULL;

    self->cap_nodes = 256;
    self->nodes = (PTNode *)malloc(sizeof(PTNode) * (size_t)self->cap_nodes);
    if (!self->nodes) {
        Py_DECREF(self);
        return PyErr_NoMemory();
    }
    self->n_nodes = 0;

    self->cap_values = 64;
    self->values = (PyObject **)malloc(sizeof(PyObject *) * (size_t)self->cap_values);
    if (!self->values) {
        free(self->nodes);
        Py_DECREF(self);
        return PyErr_NoMemory();
    }
    self->n_values = 0;
    self->built = 0;

    /* Create root node (index 0) */
    if (pt_new_node(self) < 0) {
        free(self->nodes);
        free(self->values);
        Py_DECREF(self);
        return PyErr_NoMemory();
    }

    return (PyObject *)self;
}

static void
PrefixTrie_dealloc(PrefixTrieObject *self)
{
    for (int i = 0; i < self->n_values; i++) {
        Py_XDECREF(self->values[i]);
    }
    free(self->values);
    free(self->nodes);
    Py_TYPE(self)->tp_free((PyObject *)self);
}

/* ------------------------------------------------------------------ */
/* add_prefix(key: str, value: object)                                */
/* ------------------------------------------------------------------ */

static PyObject *
PrefixTrie_add_prefix(PrefixTrieObject *self, PyObject *args)
{
    const char *key;
    Py_ssize_t key_len;
    PyObject *value;

    if (!PyArg_ParseTuple(args, "s#O", &key, &key_len, &value))
        return NULL;

    if (self->built) {
        PyErr_SetString(PyExc_RuntimeError,
                        "cannot add_prefix after build()");
        return NULL;
    }

    int cur = 0;  /* root */
    for (Py_ssize_t i = 0; i < key_len; i++) {
        unsigned char c = (unsigned char)key[i];
        if (self->nodes[cur].children[c] < 0) {
            int nid = pt_new_node(self);
            if (nid < 0) return PyErr_NoMemory();
            self->nodes[cur].children[c] = nid;
        }
        cur = self->nodes[cur].children[c];
    }

    /* Store value at terminal node */
    int vid = pt_new_value(self, value);
    if (vid < 0) return PyErr_NoMemory();
    self->nodes[cur].output = vid;

    Py_RETURN_NONE;
}

/* ------------------------------------------------------------------ */
/* build() — freeze the trie                                          */
/* ------------------------------------------------------------------ */

static PyObject *
PrefixTrie_build(PrefixTrieObject *self, PyObject *Py_UNUSED(ignored))
{
    if (self->built) {
        PyErr_SetString(PyExc_RuntimeError, "trie already built");
        return NULL;
    }
    self->built = 1;
    Py_RETURN_NONE;
}

/* ------------------------------------------------------------------ */
/* iter(text: str) -> list[object]                                    */
/* ------------------------------------------------------------------ */

static PyObject *
PrefixTrie_iter(PrefixTrieObject *self, PyObject *args)
{
    const char *text;
    Py_ssize_t text_len;

    if (!PyArg_ParseTuple(args, "s#", &text, &text_len))
        return NULL;

    if (!self->built) {
        PyErr_SetString(PyExc_RuntimeError,
                        "call build() before iter()");
        return NULL;
    }

    PyObject *result = PyList_New(0);
    if (!result) return NULL;

    PTNode *nodes = self->nodes;
    int state = 0;

    for (Py_ssize_t i = 0; i < text_len; i++) {
        unsigned char c = (unsigned char)text[i];
        int next = nodes[state].children[c];
        if (next < 0) break;
        state = next;
        if (nodes[state].output >= 0) {
            PyObject *val = self->values[nodes[state].output];
            if (PyList_Append(result, val) < 0) {
                Py_DECREF(result);
                return NULL;
            }
        }
    }

    return result;
}

/* ------------------------------------------------------------------ */
/* Type definition                                                    */
/* ------------------------------------------------------------------ */

static PyMethodDef PrefixTrie_methods[] = {
    {"add_prefix", (PyCFunction)PrefixTrie_add_prefix, METH_VARARGS,
     "add_prefix(key: str, value: object) — insert prefix into trie"},
    {"build", (PyCFunction)PrefixTrie_build, METH_NOARGS,
     "build() — freeze the trie (no more additions)"},
    {"iter", (PyCFunction)PrefixTrie_iter, METH_VARARGS,
     "iter(text: str) -> list[object] — collect all matching prefix values"},
    {NULL, NULL, 0, NULL}
};

static PyTypeObject PrefixTrieType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "dux._prefix_trie.PrefixTrie",
    .tp_basicsize = sizeof(PrefixTrieObject),
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "Prefix trie for O(m) multi-prefix startswith matching.",
    .tp_new = PrefixTrie_new,
    .tp_dealloc = (destructor)PrefixTrie_dealloc,
    .tp_methods = PrefixTrie_methods,
};

/* ------------------------------------------------------------------ */
/* Module definition (multi-phase init for free-threaded compat)      */
/* ------------------------------------------------------------------ */

static int
prefix_trie_exec(PyObject *m)
{
    if (PyType_Ready(&PrefixTrieType) < 0)
        return -1;
    if (PyModule_AddObjectRef(m, "PrefixTrie",
                              (PyObject *)&PrefixTrieType) < 0)
        return -1;
    return 0;
}

/* Thread-safety contract: the trie is built once via add_prefix +
 * build (single-threaded), then only read during iter().
 * Concurrent iter() calls are safe since they only read shared state.
 * This justifies Py_MOD_GIL_NOT_USED for free-threaded Python. */
static PyModuleDef_Slot prefix_trie_slots[] = {
    {Py_mod_exec, prefix_trie_exec},
#ifdef Py_GIL_DISABLED
    {Py_mod_gil, Py_MOD_GIL_NOT_USED},
#endif
    {0, NULL}
};

static struct PyModuleDef prefix_trie_module = {
    PyModuleDef_HEAD_INIT,
    .m_name = "dux._prefix_trie",
    .m_doc = "Prefix trie for multi-prefix startswith matching (GIL-free).",
    .m_size = 0,
    .m_slots = prefix_trie_slots,
};

PyMODINIT_FUNC
PyInit__prefix_trie(void)
{
    return PyModuleDef_Init(&prefix_trie_module);
}
