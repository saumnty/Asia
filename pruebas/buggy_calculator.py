def add_numbers(a, b):
    return a + b


def divide_numbers(a, b):
    if b == 0:
        print("Error: División entre cero")
        return None
    return a / b


def average_numbers(numbers):
    if numbers is None or len(numbers) == 0:
        print("Error: Lista vacía o None")
        return None
    total = sum(numbers)
    return total / len(numbers)


def clean_user_name(name):
    if name is None or not isinstance(name, str):
        return ""
    return name.strip().lower()


def get_first_item(items):
    if items is None or len(items) == 0:
        print("Error: Lista vacía o None")
        return None
    return items[0]