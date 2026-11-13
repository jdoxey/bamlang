// A small structured IR between lowering and text emission.
use crate::ast::Type;
use crate::check::StructInfo;
use std::collections::BTreeSet;

#[derive(Clone, PartialEq, Debug)]
pub enum LTy { I64, I1, Ptr, Void, Token, Named(String) }

#[derive(Clone, Debug)]
pub enum Op { Reg(usize, LTy), Int(i64), Global(String), Undef(LTy) }

#[derive(Clone, Debug)]
pub struct CallInfo { pub dst: Option<usize>, pub ret: LTy, pub callee: String, pub args: Vec<Op>, pub funclet: Option<usize> }

#[derive(Debug)]
pub enum Inst {
    Alloca { dst: usize, ty: LTy },
    Store { val: Op, ptr: Op },
    Load { dst: usize, ty: LTy, ptr: Op },
    Bin { dst: usize, op: &'static str, a: Op, b: Op },
    Icmp { dst: usize, pred: &'static str, a: Op, b: Op },
    Field { dst: usize, sty: String, ptr: Op, idx: usize },
    Elem { dst: usize, base: Op, idx: i64 },
    Extract { dst: usize, ty: LTy, agg: Op, idx: usize },
    Insert { dst: usize, ty: LTy, agg: Op, val: Op, idx: usize },
    Call(CallInfo),
    DbgDeclare { ptr: Op, var: usize },
    Landing { dst: usize, catch: bool },
    CleanupPad { dst: usize },
    CatchPad { dst: usize, sw: usize },
}

#[derive(Debug)]
pub enum Term {
    Br(String),
    CondBr(Op, String, String),
    Ret(Option<Op>),
    Unreachable,
    Resume(Op),
    Invoke(CallInfo, String, String),
    CleanupRet(usize),
    CatchRet(usize, String),
    CatchSwitch { dst: usize, handler: String },
}

pub struct Block { pub label: String, pub insts: Vec<(Inst, u32)>, pub term: Option<(Term, u32)> }
pub struct DbgVar { pub name: String, pub ty: Type, pub line: u32, pub arg: Option<usize> }

pub struct Func {
    pub name: String,
    pub disp: String,
    pub ret: LTy,
    pub sig: Vec<Type>,
    pub ret_ty: Type,
    pub params: Vec<(usize, LTy)>,
    pub blocks: Vec<Block>,
    pub dbgvars: Vec<DbgVar>,
    pub eh: bool,
    pub line: u32,
}

pub struct Module {
    pub structs: Vec<StructInfo>,
    pub funcs: Vec<Func>,
    pub strings: Vec<String>,
    pub cov_lines: BTreeSet<u32>,
    pub ranges: Vec<(String, u32, u32)>,
}
