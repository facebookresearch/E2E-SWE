"""Exact round-trip tests for the fparser2 Fortran parser (probe)."""

from fparser.common.readfortran import FortranStringReader
from fparser.common.sourceinfo import FortranFormat
from fparser.two.parser import ParserFactory

_PARSER = ParserFactory().create(std="f2008")


def _parse(code, free=True):
    reader = FortranStringReader(code, ignore_comments=False)
    reader.set_format(FortranFormat(free, False))
    return str(_PARSER(reader))


def test_fx_do_loop():
    assert (
        _parse(
            "      program p\n      do 10 i = 1, 10\n   10 continue\n      end\n",
            free=False,
        )
        == "PROGRAM p\n  DO 10 i = 1, 10\n10 CONTINUE\nEND"
    )


def test_fx_do_assign():
    assert (
        _parse("      program p\n      do10i = 1.10\n      end\n", free=False)
        == "PROGRAM p\n  do10i = 1.10\nEND"
    )


def test_fx_continuation():
    assert (
        _parse(
            "      program p\n      x = 1 +\n     &    2 + 3\n      end\n", free=False
        )
        == "PROGRAM p\n  x = 1 + 2 + 3\nEND"
    )


def test_fx_arith_if():
    assert (
        _parse(
            "      program p\n      if (x) 10, 20, 30\n   10 x = 1\n   20 x = 2\n   30 x = 3\n      end\n",
            free=False,
        )
        == "PROGRAM p\n  IF (x) 10, 20, 30\n10 x = 1\n20 x = 2\n30 x = 3\nEND"
    )


def test_decl_param():
    assert (
        _parse("program p\n  integer, parameter :: n = 10\nend program p\n", free=True)
        == "PROGRAM p\n  INTEGER, PARAMETER :: n = 10\nEND PROGRAM p"
    )


def test_decl_complex():
    assert (
        _parse(
            "program p\n  real(kind=8), dimension(:,:), allocatable :: a\nend program p\n",
            free=True,
        )
        == "PROGRAM p\n  REAL(KIND = 8), DIMENSION(:, :), ALLOCATABLE :: a\nEND PROGRAM p"
    )


def test_expr_prec():
    assert (
        _parse("program p\n  x = a + b * c - d / e\nend program p\n", free=True)
        == "PROGRAM p\n  x = a + b * c - d / e\nEND PROGRAM p"
    )


def test_expr_logical():
    assert (
        _parse("program p\n  l = a .and. b .or. .not. c\nend program p\n", free=True)
        == "PROGRAM p\n  l = a .AND. b .OR. .NOT. c\nEND PROGRAM p"
    )


def test_derived_type():
    assert (
        _parse(
            "module m\n  type :: point\n    real :: x, y\n  end type point\nend module m\n",
            free=True,
        )
        == "MODULE m\n  TYPE :: point\n    REAL :: x, y\n  END TYPE point\nEND MODULE m"
    )


def test_subroutine():
    assert (
        _parse(
            "subroutine s(a, b)\n  integer, intent(in) :: a\n  integer, intent(out) :: b\n  b = a + 1\nend subroutine s\n",
            free=True,
        )
        == "SUBROUTINE s(a, b)\n  INTEGER, INTENT(IN) :: a\n  INTEGER, INTENT(OUT) :: b\n  b = a + 1\nEND SUBROUTINE s"
    )


def test_if_elseif():
    assert (
        _parse(
            "program p\n  if (a > 0) then\n    x = 1\n  else if (a < 0) then\n    x = -1\n  else\n    x = 0\n  end if\nend program p\n",
            free=True,
        )
        == "PROGRAM p\n  IF (a > 0) THEN\n    x = 1\n  ELSE IF (a < 0) THEN\n    x = - 1\n  ELSE\n    x = 0\n  END IF\nEND PROGRAM p"
    )


def test_do_while():
    assert (
        _parse(
            "program p\n  do while (i < 10)\n    i = i + 1\n  end do\nend program p\n",
            free=True,
        )
        == "PROGRAM p\n  DO WHILE (i < 10)\n    i = i + 1\n  END DO\nEND PROGRAM p"
    )


def test_select_case():
    assert (
        _parse(
            "program p\n  select case (n)\n  case (1)\n    x = 1\n  case default\n    x = 0\n  end select\nend program p\n",
            free=True,
        )
        == "PROGRAM p\n  SELECT CASE (n)\n  CASE (1)\n    x = 1\n  CASE DEFAULT\n    x = 0\n  END SELECT\nEND PROGRAM p"
    )


def test_where_stmt():
    assert (
        _parse("program p\n  where (a > 0) b = 1\nend program p\n", free=True)
        == "PROGRAM p\n  WHERE (a > 0) b = 1\nEND PROGRAM p"
    )


def test_module_contains():
    assert (
        _parse(
            "module m\ncontains\n  function f(x) result(y)\n    real :: x, y\n    y = x * 2\n  end function f\nend module m\n",
            free=True,
        )
        == "MODULE m\n  CONTAINS\n  FUNCTION f(x) RESULT(y)\n    REAL :: x, y\n    y = x * 2\n  END FUNCTION f\nEND MODULE m"
    )


def test_interface_block():
    assert (
        _parse(
            "module m\n  interface\n    subroutine s(a)\n      integer :: a\n    end subroutine s\n  end interface\nend module m\n",
            free=True,
        )
        == "MODULE m\n  INTERFACE\n    SUBROUTINE s(a)\n      INTEGER :: a\n    END SUBROUTINE s\n  END INTERFACE\nEND MODULE m"
    )


def test_complex_decl2():
    assert (
        _parse(
            "program p\n  character(len=*), parameter :: name = 'hi'\nend program p\n",
            free=True,
        )
        == "PROGRAM p\n  CHARACTER(LEN = *), PARAMETER :: name = 'hi'\nEND PROGRAM p"
    )


def test_array_constructor():
    assert (
        _parse(
            "program p\n  integer :: a(3) = (/ 1, 2, 3 /)\nend program p\n", free=True
        )
        == "PROGRAM p\n  INTEGER :: a(3) = (/1, 2, 3/)\nEND PROGRAM p"
    )


def test_nested_do():
    assert (
        _parse(
            "program p\n  do i = 1, n\n    do j = 1, m\n      a(i,j) = i + j\n    end do\n  end do\nend program p\n",
            free=True,
        )
        == "PROGRAM p\n  DO i = 1, n\n    DO j = 1, m\n      a(i, j) = i + j\n    END DO\n  END DO\nEND PROGRAM p"
    )


def test_pointer_assoc():
    assert (
        _parse(
            "program p\n  real, pointer :: p\n  real, target :: t\n  p => t\nend program p\n",
            free=True,
        )
        == "PROGRAM p\n  REAL, POINTER :: p\n  REAL, TARGET :: t\n  p => t\nEND PROGRAM p"
    )


def test_format_stmt():
    assert (
        _parse(
            "      program p\n      write(*,100) x\n  100 format(1x, f10.2)\n      end\n",
            free=False,
        )
        == "PROGRAM p\n  WRITE(*, 100) x\n100 FORMAT(1X, F10.2)\nEND"
    )


# --- Coverage-gap additions: constructs fparser supports that the probe didn't exercise ---
def test_parameter_stmt():
    assert (
        _parse("program p\n  parameter (n = 10)\nend program p\n", free=True)
        == "PROGRAM p\n  PARAMETER(n = 10)\nEND PROGRAM p"
    )


def test_computed_goto():
    assert (
        _parse(
            "program p\n  go to (10, 20, 30) i\n10 continue\n20 continue\n30 continue\nend program p\n",
            free=True,
        )
        == "PROGRAM p\n  GO TO (10, 20, 30), i\n10 CONTINUE\n20 CONTINUE\n30 CONTINUE\nEND PROGRAM p"
    )


def test_old_real8():
    assert (
        _parse("program p\n  real*8 :: r\nend program p\n", free=True)
        == "PROGRAM p\n  REAL*8 :: r\nEND PROGRAM p"
    )


def test_associate():
    assert (
        _parse(
            "program p\n  associate (a => b + c)\n    x = a\n  end associate\nend program p\n",
            free=True,
        )
        == "PROGRAM p\n  ASSOCIATE(a => b + c)\n    x = a\n  END ASSOCIATE\nEND PROGRAM p"
    )


def test_forall():
    assert (
        _parse("program p\n  forall (i = 1:n) a(i) = i\nend program p\n", free=True)
        == "PROGRAM p\n  FORALL (i = 1 : n) a(i) = i\nEND PROGRAM p"
    )


def test_block_construct():
    assert (
        _parse(
            "program p\n  block\n    integer :: z\n    z = 1\n  end block\nend program p\n",
            free=True,
        )
        == "PROGRAM p\n  BLOCK\n    INTEGER :: z\n    z = 1\n  END BLOCK\nEND PROGRAM p"
    )


def test_multi_stmt_semicolon():
    assert (
        _parse("program p\n  x = 1; y = 2\nend program p\n", free=True)
        == "PROGRAM p\n  x = 1\n  y = 2\nEND PROGRAM p"
    )


# --- No-reserved-words stress: statement-starter keywords used as ordinary variables ---
# A single representative program exercises the "Fortran has no reserved words" contract across a
# broad spread of statement-starter keywords (declaration, control, and I/O starters together),
# each used as an ordinary integer variable in a chain of assignments.
def test_nr_combined_keywords():
    assert (
        _parse(
            "program p\n  integer :: if, real, do, where, data, write, read, format, call, allocate, type, common, save, go\n  if = 3\n  real = if + 5\n  do = real\n  where = do + if\n  data = where\n  write = data\n  read = write + 2\n  format = read\n  call = format\n  allocate = call\n  type = allocate\n  common = type\n  save = common * 2\n  go = save + do\nend program p\n",
            free=True,
        )
        == "PROGRAM p\n  INTEGER :: if, real, do, where, data, write, read, format, call, allocate, type, common, save, go\n  if = 3\n  real = if + 5\n  do = real\n  where = do + if\n  data = where\n  write = data\n  read = write + 2\n  format = read\n  call = format\n  allocate = call\n  type = allocate\n  common = type\n  save = common * 2\n  go = save + do\nEND PROGRAM p"
    )


# String concatenation (//) — a documented scope construct not exercised elsewhere.
def test_string_concat():
    assert (
        _parse("program p\n  s = a // b // c\nend program p\n", free=True)
        == "PROGRAM p\n  s = a // b // c\nEND PROGRAM p"
    )
