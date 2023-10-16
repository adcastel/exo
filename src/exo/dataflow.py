from abc import ABC, abstractmethod
from enum import Enum
from itertools import chain
from typing import Mapping, Any
from asdl_adt import ADT, validators

from .builtins import BuiltIn
from .configs import Config
from .memory import Memory
from .prelude import Sym, SrcInfo, extclass
from .LoopIR import LoopIR, Alpha_Rename, SubstArgs, LoopIR_Do, Operator, T, Identifier

# --------------------------------------------------------------------------- #
# DataflowIR definition
# --------------------------------------------------------------------------- #

# Ask Gilbert about value dependent analysis
"""
n : R[n+1]
for i in seq(0, n):
    x[i] = sin(i)
for i in seq(0, n):
    x[i+1] = sin(i+1)

Want to analyze that x[i] = sin(i) and x[i+1] = sin(i+1) write the same value to the same memory.

"""

# TODO:
# implement pretty printing as well


def validateAbsEnv(obj):
    if not isinstance(obj, dict):
        raise ValidationError(AbsEnv, type(obj))
    for key in obj:
        if not isinstance(key, Sym):
            raise ValidationError(Sym, key)
    return obj


DataflowIR = ADT(
    """
module DataflowIR {
    proc = ( name    name,
             fnarg*  args,
             expr*   preds,
             block   body,
             srcinfo srcinfo )

    fnarg  = ( sym     name,
               type    type,
               srcinfo srcinfo )

    block = ( stmt* stmts, absenv* ctxts ) -- len(stmts) + 1 == len(ctxts)

    stmt = Assign( sym name, type type, string? cast, expr* idx, expr rhs )
         | Reduce( sym name, type type, string? cast, expr* idx, expr rhs )
         | WriteConfig( sym config_field, expr rhs )
         | Pass()
         | If( expr cond, block body, block orelse )
         | Seq( sym iter, expr lo, expr hi, block body )
         | Alloc( sym name, type type )
         | InlinedCall( proc f, block body ) -- f is only there for comments
         attributes( srcinfo srcinfo )

    expr = Read( sym name, expr* idx )
         | Const( object val )
         | USub( expr arg )  -- i.e.  -(...)
         | BinOp( binop op, expr lhs, expr rhs )
         | BuiltIn( builtin f, expr* args )
         | StrideExpr( sym name, int dim )
         | ReadConfig( sym config_field )
         attributes( type type, srcinfo srcinfo )

}""",
    ext_types={
        "name": validators.instance_of(Identifier, convert=True),
        "sym": Sym,
        "builtin": BuiltIn,
        "config": Config,
        "binop": validators.instance_of(Operator, convert=True),
        "type": LoopIR.type,
        "absenv": validateAbsEnv,
        "srcinfo": SrcInfo,
    },
    memoize={},
)

from . import dataflow_pprint

# --------------------------------------------------------------------------- #
# Top Level Call to Dataflow analysis
# --------------------------------------------------------------------------- #


class LoopIR_to_DataflowIR:
    def __init__(self, proc):
        self.loopir_proc = proc
        self.dataflow_proc = self.map_proc(self.loopir_proc)

    def result(self):
        return self.dataflow_proc

    def map_proc(self, p):
        df_args = self._map_list(self.map_fnarg, p.args)
        df_preds = self.map_exprs(p.preds)
        df_body = self.map_stmts(p.body)
        # TODO: Gilbert
        block = DataflowIR.block(df_body, [{}] * (len(df_body) + 1))

        return DataflowIR.proc(p.name, df_args, df_preds, block, p.srcinfo)

    def map_fnarg(self, a):
        return DataflowIR.fnarg(a.name, a.type, a.srcinfo)

    def map_stmts(self, stmts):
        return self._map_list(self.map_s, stmts)

    def map_exprs(self, exprs):
        return self._map_list(self.map_e, exprs)

    def map_s(self, s):
        if isinstance(s, (LoopIR.Call, LoopIR.WindowStmt)):
            raise NotImplementedError(
                "LoopIR.Call and LoopIR.WindowStmt should be inlined when we reach here!"
            )

        if isinstance(s, (LoopIR.Assign, LoopIR.Reduce)):
            df_idx = self.map_exprs(s.idx)
            df_rhs = self.map_e(s.rhs)
            if isinstance(s, LoopIR.Assign):
                return DataflowIR.Assign(
                    s.name, s.type, s.cast, df_idx, df_rhs, s.srcinfo
                )
            else:
                return DataflowIR.Reduce(
                    s.name, s.type, s.cast, df_idx, df_rhs, s.srcinfo
                )

        elif isinstance(s, LoopIR.WriteConfig):
            # TODO: Confirm with Gilbert!
            df_config_sym = Sym(f"{config.name}_{field}")
            df_rhs = self.map_e(s.rhs)

            return DataflowIR_WriteConfig(df_config_sym, df_rhs, s.srcinfo)

        elif isinstance(s, LoopIR.If):
            df_cond = self.map_e(s.cond)
            df_body = self.map_stmts(s.body)
            df_orelse = self.map_stmts(s.orelse)

            return DataflowIR.If(df_cond, df_body, df_orelse, s.srcinfo)

        elif isinstance(s, LoopIR.Seq):
            df_lo = self.map_e(s.lo)
            df_hi = self.map_e(s.hi)
            df_body = self.map_stmts(s.body)

            return DataflowIR.Seq(s.iter, df_lo, df_hi, df_body, s.srcinfo)

        elif isinstance(s, LoopIR.Alloc):
            return DataflowIR.Alloc(s.name, s.type, s.srcinfo)

        elif isinstance(s, LoopIR.Pass):
            return DataflowIR.Pass(s.srcinfo)

        else:
            raise NotImplementedError(f"bad case {type(s)}")

    def map_e(self, e):
        if isinstance(e, LoopIR.Read):
            df_idx = self.map_exprs(e.idx)
            return DataflowIR.Read(e.name, df_idx, e.type, e.srcinfo)

        elif isinstance(e, LoopIR.BinOp):
            df_lhs = self.map_e(e.lhs)
            df_rhs = self.map_e(e.rhs)
            return DataflowIR.BinOp(e.op, df_lhs, df_rhs, e.type, e.srcinfo)

        elif isinstance(e, LoopIR.BuiltIn):
            df_args = self.map_exprs(e.args)
            return DataflowIR.BuiltIn(e.f, df_args, e.type, e.srcinfo)

        elif isinstance(e, LoopIR.USub):
            df_arg = self.map_e(e.arg)
            return DataflowIR.USub(df_arg, e.type, e.srcinfo)

        elif isinstance(e, LoopIR.WindowExpr):
            raise NotImplementedError("WindowExpr should not appear here!")

        elif isinstance(e, LoopIR.ReadConfig):
            # TODO: This needs to coodinate with Writeconfig
            raise NotImplementedError("Implement ReadConfig")

        elif isinstance(e, LoopIR.Const):
            return DataflowIR.Const(e.val, e.type, e.srcinfo)

        elif isinstance(e, LoopIR.StrideExpr):
            return DataflowIR.StrideExpr(e.name, e.dim, e.type, e.srcinfo)

        else:
            raise NotImplementedError(f"bad case {type(e)}")

    @staticmethod
    def _map_list(fn, nodes):
        return [fn(n) for n in nodes]


def dataflow_analysis(proc: LoopIR.proc) -> DataflowIR.proc:
    # step 1 - convert LoopIR to DataflowIR with empty contexts (i.e. AbsEnvs)
    # TODO: inline functioncall -> inline windowstmt -> lowering
    # FIXME: new_proc = inline_func(proc)
    # FIXME: new_proc = inline_windowstmt(proc)
    datair = LoopIR_to_DataflowIR(proc).result()

    # step 2 - run abstract interpretation algorithm
    #           to populate contexts with sound values
    # TODO: call constant propagation
    # datair = ConstantPropagation()

    return datair


# --------------------------------------------------------------------------- #
# Abstract Interpretation on DataflowIR
# --------------------------------------------------------------------------- #


class AbstractInterpretation(ABC):
    def __init__(self, proc: DataflowIR.proc):
        self.proc = proc

        # setup initial values
        init_env = self.proc.body.ctxts[0]
        for a in proc.args:
            init_env[a.name] = self.abs_init_val(a.name, a.type)

        # We probably ought to somehow use precondition assertions
        # TODO: leave it for now
        # { n == 16; }
        for p in proc.preds:
            self.assume_pred(p, init_env)

        self.fix_block(self.proc.body)

    def fix_block(self, body: DataflowIR.block):
        """Assumes any inputs have already been set in body.ctxts[0]"""
        assert len(body.stmts) + 1 == len(body.ctxts)

        for s, pre, post in zip(body.stmts, body.ctxts[:-1], body.ctxts[1:]):
            self.fix_stmt(pre, s, post)

    def fix_stmt(self, pre_env, stmt: DataflowIR.stmt, post_env):
        if isinstance(stmt, (DataflowIR.Assign, DataflowIR.Reduce)):
            # TODO: Design approach for parameterization over idx

            # if reducing, then expand to x = x + rhs
            rhs_e = stmt.rhs
            if isinstance(stmt, DataflowIR.Reduce):
                read_buf = DataflowIR.Read(stmt.name, stmt.idx)
                rhs_e = DataflowIR.BinOp("+", read_buf, rhs_e)
            # now we can handle both cases uniformly
            rval = self.fix_expr(pre_env, rhs_e)
            # need to be careful for buffers (no overwrite guarantee)
            if len(stmt.idx) > 0:
                rval = self.abs_join(pre_env[stmt.name], rval)
            post_env[stmt.name] = rval

            # propagate un-touched variables
            for nm in pre_env:
                if nm != stmt.name:
                    post_env[nm] = pre_env[nm]

        elif isinstance(stmt, DataflowIR.WriteConfig):
            rval = self.fix_expr(pre_env, stmt.rhs)
            post_env[stmt.config_field] = rval

            # propagate un-touched variables
            for nm in pre_env:
                if nm != stmt.config_field:
                    post_env[nm] = pre_env[nm]

        elif isinstance(stmt, DataflowIR.Pass):
            # propagate un-touched variables
            for nm in pre_env:
                post_env[nm] = pre_env[nm]

        elif isinstance(stmt, DataflowIR.Alloc):
            # TODO: Add support for parameterization over idx?

            post_env[stmt.name] = self.abs_alloc_val(stmt.name, stmt.type)

            # propagate un-touched variables
            for nm in pre_env:
                post_env[nm] = pre_env[nm]

        elif isinstance(stmt, DataflowIR.If):
            # TODO: Add support for path-dependency in analysis
            # TODO: Add support for "I know cond is true!"
            pre_body, post_body = stmt.body.ctxts[0], stmt.body.ctxts[-1]
            pre_else, post_else = stmt.orelse.ctxts[0], stmt.orelse.ctxts[-1]

            for nm, val in pre_env.items():
                pre_body[nm] = val
                pre_else[nm] = val

            self.fix_block(stmt.body)
            self.fix_block(stmt.orelse)

            for nm in pre_env:
                bodyval = post_body[nm]
                elseval = post_else[nm]
                val = self.abs_join(bodyval, elseval)
                post_env[nm] = val

        elif isinstance(stmt, DataflowIR.Seq):
            # TODO: Add support for loop-condition analysis in some way?

            # set up the loop body for fixed-point iteration
            pre_body = stmt.body.ctxts[0]
            for nm, val in pre_env.items():
                pre_body[nm] = val
            # initialize the loop iteration variable
            lo = self.fix_expr(pre_env, stmt.lo)
            hi = self.fix_expr(pre_env, stmt.hi)
            pre_body[stmt.iter] = self.abs_iter_val(lo, hi)

            # run this loop until we reach a fixed-point
            at_fixed_point = False
            while not at_fixed_point:
                # propagate in the loop
                self.fix_block(stmt.body)
                at_fixed_point = True
                # copy the post-values for the loop back around to
                # the pre-values, by joining them together
                for nm, prev_val in pre_body.items():
                    next_val = stmt.body.ctxts[-1][nm]
                    val = self.abs_join(prev_val, next_val)
                    at_fixed_point = at_fixed_point and prev_val == val
                    pre_body[nm] = val

            # determine the post-env as join of pre-env and loop results
            for nm, pre_val in pre_env.items():
                loop_val = stmt.body.ctxts[-1][nm]
                post_env[nm] = self.abs_join(pre_val, loop_val)

        elif isinstance(stmt, DataflowIR.InlinedCall):
            # TODO: Decide how Inlined Calls work
            pre_body, post_body = stmt.body.ctxts[0], stmt.body.ctxts[-1]
            pre_else, post_else = stmt.orelse.ctxts[0], stmt.orelse.ctxts[-1]

            for nm, val in pre_env.items():
                stmt.body.ctxts[0][nm] = val

            self.fix_block(stmt.body)

            # Left Off: Oh No, do we preserve variable names when inlining?
        else:
            assert False, f"bad case: {type(stmt)}"

    def fix_expr(self, pre_env, expr: DataflowIR.expr):
        if isinstance(expr, DataflowIR.Read):
            return pre_env[expr.name]
        elif isinstance(expr, DataflowIR.Const):
            return self.abs_const(expr.val, expr.type)
        elif isinstance(expr, DataflowIR.USub):
            arg = self.fix_expr(pre_env, expr.arg)
            return self.abs_usub(arg)
        elif isinstance(expr, DataflowIR.BinOp):
            lhs = self.fix_expr(pre_env, expr.lhs)
            rhs = self.fix_expr(pre_env, expr.rhs)
            return self.abs_binop(expr.op, lhs, rhs)
        elif isinstance(expr, DataflowIR.BuiltIn):
            args = [self.fix_expr(pre_env, a) for a in expr.args]
            return self.abs_builtin(expr.f, args)
        elif isinstance(expr, DataflowIR.StrideExpr):
            return self.abs_stride_expr(expr.name, expr.dim)
        elif isinstance(expr, DataflowIR.ReadConfig):
            return pre_env[expr.config_field]
        else:
            assert False, f"bad case {type(expr)}"

    @abstractmethod
    def abs_init_val(self, name, typ):
        """Define initial argument values"""

    @abstractmethod
    def abs_alloc_val(self, name, typ):
        """Define initial value of an allocation"""

    @abstractmethod
    def abs_iter_val(self, lo, hi):
        """Define value of an iteration variable"""

    @abstractmethod
    def abs_stride_expr(self, name, dim):
        """Define abstraction of a specific stride expression"""

    @abstractmethod
    def abs_const(self, val, typ):
        """Define abstraction of a specific constant value"""

    @abstractmethod
    def abs_join(self, lval, rval):
        """Define join in the abstract value lattice"""

    @abstractmethod
    def abs_binop(self, op, lval, rval):
        """Implement transfer function abstraction for binary operations"""

    @abstractmethod
    def abs_usub(self, arg):
        """Implement transfer function abstraction for unary subtraction"""

    @abstractmethod
    def abs_builtin(self, builtin, args):
        """Implement transfer function abstraction for built-ins"""


AbstractDomains = ADT(
    """
module AbstractDomains {
    cprop = CTop() | CBot()
          | Const( object val, type type )
          | CStrideExpr( sym name, int dim )
    
    iprop = ITop() | IBot()
          | Interval( int lo, int hi ) -- use for integers
}
""",
    ext_types={
        "type": LoopIR.type,
        "sym": Sym,
    },
    memoize={"CTop", "CBot", "Const", "ITop", "IBot", "Interval", "IConst"},
)
A = AbstractDomains


class ConstantPropagation(AbstractInterpretation):
    def abs_init_val(self, name, typ):
        return A.CTop()

    def abs_alloc_val(self, name, typ):
        return A.CTop()

    def abs_iter_val(self, lo, hi):
        return A.CTop()

    def abs_stride_expr(self, name, dim):
        return A.CStrideExpr(name, dim)

    def abs_const(self, val, typ):
        return A.Const(val, typ)

    def abs_join(self, lval: A.cprop, rval: A.cprop):
        if lval == A.CBot():
            return rval
        elif rval == A.CBot():
            return lval
        elif lval == A.CTop() or rval == A.CTop():
            return A.CTop()
        else:
            assert isinstance(lval, A.Const) and isinstance(rval, A.Const)
            if lval.val == rval.val:
                return lval
            else:
                return A.CTop()

    def abs_binop(self, op, lval, rval):
        if isinstance(lval, A.CBot) or isinstance(rval, A.CBot):
            return A.CBot()

        # front_ops = {"+", "-", "*", "/", "%",
        #              "<", ">", "<=", ">=", "==", "and", "or"}
        if isinstance(lval, A.Const) and isinstance(rval, A.Const):
            typ = lval.type
            if op == "+":
                val = lval + rval
            elif op == "-":
                val = lval - rval
            elif op == "*":
                val = lval * rval
            elif op == "/":
                val = lval / rval  # THIS IS WRONG
            elif op == "%":
                val = lval % rval
            else:
                typ = T.bool  # What would be bool here?
                if op == "<":
                    val = lval < rval
                elif op == ">":
                    val = lval > rval
                elif op == "<=":
                    val = lval <= rval
                elif op == ">=":
                    val = lval >= rval
                elif op == "==":
                    val = lval == rval
                elif op == "and":
                    val = lval and rval
                elif op == "or":
                    val = lval or rval
                else:
                    assert False, f"Bad Case Operator: {op}"

            return A.Const(val, typ)

        # TODO: and, or short circuiting here

        if op == "/":
            # NOTE: THIS doesn't work right for integer division...
            # c1 / c2
            # 0 / x == 0
            if isinstance(lval, A.Const) and lval.val == 0:
                return lval

        if op == "%":
            if isinstance(rval, A.Const) and rval.val == 1:
                return A.Const(0, lval.type)

        if op == "*":
            # x * 0 == 0
            if isinstance(lval, A.Const) and lval.val == 0:
                return lval
            elif isinstance(rval, A.Const) and rval.val == 0:
                return rval

        # memo
        # 0 + x == x
        # TOP + C(0) = abs({ x + y | x in conc(TOP), y in conc(C(0)) })
        #            = abs({ x + 0 | x in anything })
        #            = abs({ x | x in anything })
        #            = TOP
        return A.CTop()

    def abs_usub(self, arg):
        if isinstance(arg, A.Const):
            return A.Const(-arg.val, arg.typ)
        return arg

    def abs_builtin(self, builtin, args):
        if any([not isinstance(a, A.Const) for a in args]):
            return CTop()
        vargs = [a.val for a in args]

        # TODO: write a short circuit for select builtin
        return A.Const(builtin.interpret(vargs), args[0].typ)


class IntervalAnalysis(AbstractInterpretation):
    def abs_init_val(self, name, typ):
        return A.ITop()

    def abs_alloc_val(self, name, typ):
        return A.ITop()

    def abs_iter_val(self, lo, hi):
        if isinstance(lo, A.IBot) or isinstance(hi, A.IBot):
            return A.IBot()
        else:
            return self.abs_join(lo, hi)

    def abs_join(self, lval: A.iprop, rval: A.iprop):
        if isinstance(lval, A.ITop) or isinstance(rval, A.ITop):
            return A.ITop()
        elif isinstance(lval, A.IBot):
            return rval
        elif isinstance(rval, A.IBot):
            return lval
        else:
            assert isinstance(lval, A.Interval) and isinstance(rval, A.Interval)
            return A.Interval(min(lval.lo, rval.lo), max(lval.hi, rval.hi))
