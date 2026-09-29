"""User-facing tests for probnum functions (``probnum.functions``).

Covers callable evaluation with batching, the arithmetic algebra (sum/difference/
scaling, with flattening and scalar folding), and the ``Zero`` neutral element.
"""
import numpy as np
import pytest

from probnum.functions import LambdaFunction, ScaledFunction, SumFunction, Zero


def _lin(weights):
    """A LambdaFunction x -> x @ weights mapping input_shape (k,) to scalar output."""
    weights = np.asarray(weights, dtype=float)
    return LambdaFunction(
        lambda x: x @ weights, input_shape=(weights.size,), output_shape=()
    )


def test_function_evaluation_batches_over_leading_dims():
    """A LambdaFunction evaluates pointwise and broadcasts over arbitrary leading batch dims."""
    fn = LambdaFunction(
        lambda x: np.stack([x[..., 0] + x[..., 1], x[..., 0] - x[..., 1]], axis=-1),
        input_shape=(2,),
        output_shape=(2,),
    )
    single = fn(np.array([3.0, 1.0]))
    np.testing.assert_allclose(single, [4.0, 2.0])
    assert single.shape == (2,)

    batch = fn(np.zeros((5, 4, 2)))
    assert batch.shape == (5, 4, 2)

    with pytest.raises(ValueError):
        fn(np.zeros((3,)))  # trailing dim != input_shape


def test_sum_and_difference_evaluate_pointwise():
    """Sums and differences of functions evaluate to the pointwise sum/difference of their values."""
    f0, f1 = _lin([1.0, 2.0]), _lin([-3.0, 0.5])
    xs = np.array([[1.0, 1.0], [2.0, -1.0], [0.0, 4.0]])

    np.testing.assert_allclose((f0 + f1)(xs), f0(xs) + f1(xs))
    np.testing.assert_allclose((f0 - f1)(xs), f0(xs) - f1(xs))

    # Adding the Zero function is the identity operation.
    z = Zero(input_shape=(2,), output_shape=())
    assert (f0 + z) is f0
    np.testing.assert_allclose(z(xs), np.zeros(3))


def test_scalar_multiplication_evaluates_and_folds():
    """Scaling evaluates as a scaled function, and re-scaling does not nest ScaledFunctions."""
    f0 = _lin([2.0, -1.0])
    xs = np.array([[1.0, 3.0], [2.0, 2.0]])

    for s in (3.0, 1000.0):
        np.testing.assert_allclose((f0 * s)(xs), f0(xs) * s)
        np.testing.assert_allclose((s * f0)(xs), s * f0(xs))

    # Re-scaling an already-scaled function folds the scalars rather than nesting another layer.
    folded = (-f0) * 2.0
    assert isinstance(folded, ScaledFunction)
    assert not isinstance(folded.function, ScaledFunction)
    assert folded.scalar == pytest.approx(-2.0)
    np.testing.assert_allclose(folded(xs), -2.0 * f0(xs))


def test_sum_function_flattens_and_preserves_structure():
    """Chained additions/subtractions flatten into a single SumFunction with ordered summands."""
    f0, f1, f2 = _lin([1.0, 0.0]), _lin([0.0, 1.0]), _lin([1.0, 1.0])
    expr = f0 + f1 - f2

    assert isinstance(expr, SumFunction)
    assert len(expr.summands) == 3
    # The subtracted term appears as a (-1)-scaled function.
    assert isinstance(expr.summands[2], ScaledFunction)
    assert expr.summands[2].scalar == pytest.approx(-1.0)

    xs = np.array([[2.0, 5.0], [1.0, 1.0]])
    np.testing.assert_allclose(expr(xs), f0(xs) + f1(xs) - f2(xs))


def test_sum_function_rejects_shape_mismatch():
    """Building a SumFunction from functions with incompatible shapes raises ValueError."""
    f0 = _lin([1.0, 2.0])  # input_shape (2,)
    f1 = _lin([1.0, 2.0, 3.0])  # input_shape (3,)
    with pytest.raises(ValueError):
        SumFunction(f0, f1)
