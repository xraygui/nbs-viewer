import time as ttime

DEBUG_VARIABLES = {
    "PRINT_DEBUG": False,
    "DEBUG_CATALOG": False,
    "DEBUG_PLOTS": True,
    "cache": True,
    "dimension": False,
}


def turn_on_debugging():
    DEBUG_VARIABLES["PRINT_DEBUG"] = True


def turn_off_debugging():
    DEBUG_VARIABLES["PRINT_DEBUG"] = False


def print_debug(function_name, message, category=None):
    if DEBUG_VARIABLES["PRINT_DEBUG"] and DEBUG_VARIABLES.get(category, True):
        print(f"[{function_name}] {message}")


def time_function(function_name=None, category=None):
    # If called with string argument, return decorator function
    if isinstance(function_name, str):

        def named_decorator(function):
            def wrapper(*args, **kwargs):
                start_time = ttime.time()
                result = function(*args, **kwargs)
                end_time = ttime.time()
                print_debug(
                    function_name,
                    f"Time taken: {end_time - start_time} seconds",
                    category=category,
                )
                return result

            return wrapper

        return named_decorator

    # If called without arguments, function_name is actually the function
    elif callable(function_name):
        function = function_name
        name = function.__name__

        def wrapper(*args, **kwargs):
            start_time = ttime.time()
            result = function(*args, **kwargs)
            end_time = ttime.time()
            print_debug(name, f"Time taken: {end_time - start_time} seconds")
            return result

        return wrapper

    # Return decorator function for @time_function() case
    else:

        def decorator(function):
            name = function.__name__

            def wrapper(*args, **kwargs):
                start_time = ttime.time()
                result = function(*args, **kwargs)
                end_time = ttime.time()
                print_debug(name, f"Time taken: {end_time - start_time} seconds")
                return result

            return wrapper

        return decorator
