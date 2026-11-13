// A small structured IR between lowering and text emission.
use crate::ast::{Span, Type};
use crate::check::{EnumInfo, StructInfo};

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
    Extract { dst: usize, agg: Op, idx: Vec<usize> },
    Insert { dst: usize, agg: Op, val: Op, idx: Vec<usize> },
    Cast { dst: usize, op: &'static str, val: Op, to: LTy },
    // llvm.instrprof.increment for counter `idx` of the current function (source-based coverage).
    Prof { idx: u32 },
    Call(CallInfo),
    DbgDeclare { ptr: Op, var: usize },
    Landing { dst: usize },
    CleanupPad { dst: usize },
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
    pub ncounters: u32,
    pub regions: Vec<Region>,
}

#[derive(Clone, Copy, Debug)]
pub enum RKind { Code(u32), Branch(u32, u32) }
#[derive(Clone, Copy, Debug)]
pub struct Region { pub kind: RKind, pub span: Span }

pub struct Module {
    pub structs: Vec<StructInfo>,
    pub enums: Vec<EnumInfo>,
    pub funcs: Vec<Func>,
    pub strings: Vec<String>,
}
