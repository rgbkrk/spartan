#!/usr/bin/env python

'''Convert from numpy expression trees to the lower-level
operations supported by the backends (see `spartan.prims`).

'''

from . import expr, prims
from .. import util
from .extent import index_for_reduction, shapes_match
import numpy as N


binary_ops = set([N.add, N.subtract, N.multiply, N.divide, N.mod, N.power,
                  N.equal, N.less, N.less_equal, N.greater, N.greater_equal])


def to_structured_array(**kw):
  '''Create a structured array from the given input arrays.'''
  out = N.ndarray(kw.values()[0].shape, 
                  dtype=','.join([a.dtype.str for a in kw.itervalues()]))
  
  for k, v in kw.iteritems():
    out[k] = v
  return out

def argmin_local(index, value, axis):
  local_idx = value.argmin(axis)
  local_min = value.min(axis)

#  util.log('Index for reduction: %s %s %s',
#           index.array_shape,
#           axis,
#           index_for_reduction(index, axis))

  global_idx = index.to_global(local_idx, axis)

  new_idx = index_for_reduction(index, axis)
  new_value = to_structured_array(idx=global_idx, min=local_min)

#   print index, value.shape, axis
#   print local_idx.shape
  assert shapes_match(new_idx, new_value), (new_idx, new_value.shape)
  return [(new_idx, new_value)]

def argmin_reducer(a, b):
  return N.where(a['min'] < b['min'], a, b)

def sum_local(index, value, axis):
  return [(index_for_reduction(index, axis), N.sum(value, axis))]

def sum_reducer(a, b):
  return a + b

def binary_op(fn, inputs, kw):
  return fn(*inputs)



def compile_op(op):
  '''Convert a numpy expression tree in an Op tree.'''
  if isinstance(op, expr.LazyVal):
    return prims.Value(op._val)
  else:
    children = [compile_op(c) for c in op.children]

  if op.op in binary_ops:
    return prims.Map(children, 
                     lambda a, b: op.op(a, b))
  elif op.op == N.sum:
    return prims.Reduce(children[0],
                        op.kwargs['axis'],
                        dtype_fn = lambda input: input.dtype,
                        local_reducer_fn = sum_local,
                        combiner_fn = sum_reducer)
  elif op.op == N.argmin:
    compute_min = prims.Reduce(children[0],
                               op.kwargs['axis'],
                               dtype_fn = lambda input: 'i8,f8',
                               local_reducer_fn = argmin_local,
                               combiner_fn = argmin_reducer)
    take_indices = prims.Map(compute_min,
                             lambda tile: tile['idx'])
    return take_indices
  else:
    raise NotImplementedError, 'Compilation of %s not implemented yet.' % op.op