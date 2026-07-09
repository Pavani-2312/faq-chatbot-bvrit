cnt = 0

for a in range(1, 10):
    for c in range(a + 1, 10):
        b = (9 * a * c) / (10 * a - c)
        if b == int(b) and b != a:
            cnt += 1

print(cnt)