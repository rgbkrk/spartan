#!/usr/bin/env python

'''Local expressions.

Briefly: global expressions are over arrays, and local expressions are over tiles.

`LocalExpr`s have dependencies and can be
chained together; this allows us to construct local DAG's when optimizing,
which can then be executed or converted to parakeet code.
'''
import tempfile
import imp
import time

from spartan import util
from spartan.util import Assert
from spartan.node import Node
from traits.api import Str, List, Function, PythonValue

var_id = iter(xrange(1000000))

class CodegenException(Exception): pass

def make_var():
  '''Return a new unique key for use as a variable name'''
  return 'key_%d' % var_id.next()

class LocalCtx(Node):
  inputs = PythonValue


class LocalExpr(Node):
  '''Represents an internal operation to be performed in the context of a tile.'''
  deps = List()
  id = Int()

  def __init__(self, *args, **kw):
    super(LocalExpr, self).__init__(*args, **kw)
    self.id = expr_id.next()

  def __repr__(self):
    # return self.debug_str()
    return self.pretty_str()

  def add_dep(self, v):
    self.deps.append(v)
    assert len(self.deps) <= 2, v

  def input_names(self):
    return util.flatten([v.input_names() for v in self.deps], unique=True)


class LocalInput(LocalExpr):
  '''An externally supplied input.'''
  idx = Str() 

  def __str__(self):
    return 'V(%s)' % self.idx

  def evaluate(self, ctx):
    return ctx.inputs[self.idx]

  def input_names(self):
    return [self.idx]


class FnCallExpr(LocalExpr):
  '''Evaluate a function call.
  
  Dependencies that are variable should be specified via the ``deps`` attribute,
  and will be evaluated and supplied to the function when called.
  
  Constants (axis of a reduction, datatype, etc), can be supplied via the ``kw``
  argument.
  '''
  kw = PythonValue
  fn = PythonValue
  pretty_fn = PythonValue

  def __init__(self, *args, **kw):
    super(FnCallExpr, self).__init__(*args, **kw)
    if self.kw is None: self.kw = {}
    assert self.fn is not None

  def fn_name(self):
    if self.pretty_fn:
      return self.pretty_fn

    if hasattr(self.fn, '__module__'):
      return '%s.%s' % (self.fn.__module__, self.fn.__name__)
    elif hasattr(self.fn, '__class__'):
      return '%s.%s' % (self.fn.__class__.__module__,
                        self.fn.__name__)
    else:
      return self.fn.__name__

  def evaluate(self, ctx):
    deps = [d.evaluate(ctx) for d in self.deps]
    #util.log_info('Evaluating %s.%d [%s]', self.fn_name(), self.id, deps)
    st = time.time()
    result = self.fn(*deps, **self.kw)
    # util.log_info('Evaluated %s.%d in %.2f seconds',
    #               self.fn_name(), self.id, time.time() - st)
    return result


# The local operation of map and reduce expressions is practically
# identical.  Reductions take an axis and extent argument in
# addition to the normal function call arguments.
class LocalMapExpr(FnCallExpr):
  _op_type = 'map'

class LocalReduceExpr(FnCallExpr):
  _op_type = 'reduce'

# track source that we have already compiled via parakeet.
# parakeet requires the source file remain available in
# order to compile.
source_files = []

# memoize generated modules to avoid recompiling parakeet
# functions for the same source.
@util.memoize
def compile_parakeet_source(src):
  '''Compile source code defining a parakeet function.'''
  util.log_debug('Compiling parakeet source.')
  tmpfile = tempfile.NamedTemporaryFile(delete=True, prefix='spartan-local-', suffix='.py')
  tmpfile.write(src)
  tmpfile.flush()
  
  #util.log_info('File: %s, Source: \n %s \n', tmpfile.name, src)

  #os.rename(tmpfile.name, srcfile)
  #atexit.register(lambda: os.remove(srcfile))

  try:
    module = imp.load_source('parakeet_temp', tmpfile.name)
  except Exception, ex:
    util.log_info('Failed to build parakeet wrapper')
    util.log_debug('Source was: %s', src)
    raise CodegenException(ex.message, ex.args)
  
  source_files.append(tmpfile)
  return module._jit_fn


class ParakeetExpr(LocalExpr):
  deps = PythonValue
  source = PythonValue

  def fn_name(self):
    return 'parakeet'

  def evaluate(self, ctx):
    names = self.input_names()
    fn = compile_parakeet_source(self.source)
    
    kw_args = {}
    for var in names:
      value = ctx.inputs[var]
      kw_args[var] = value
    
    if FLAGS.use_cuda:
      return fn(_backend='cuda', **kw_args)
    else:
      return fn(**kw_args)

from spartan.config import FLAGS, BoolFlag
FLAGS.add(BoolFlag('use_cuda', default=False))

