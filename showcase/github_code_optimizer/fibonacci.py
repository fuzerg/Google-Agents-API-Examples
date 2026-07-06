def fibonacci(n):
    """
    A simple recursive implementation of Fibonacci numbers.
    This implementation has exponential time complexity O(2^n).
    """
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)
