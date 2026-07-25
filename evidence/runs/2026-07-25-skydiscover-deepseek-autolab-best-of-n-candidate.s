; Naive dot product — maximum stalls, no scheduling, single accumulator
; Kernel: sum = A[0]*B[0] + A[1]*B[1] + ... + A[511]*B[511]
;
; Memory layout (word-addressed):
;   A[0..511]   at addresses   0..511
;   B[0..511]   at addresses 512..1023
;
; Registers:
;   r0 = 0 (always zero)
;   r1 = sum  (result — must be in r1 at halt)
;   r2 = loop counter i
;   r3 = N = 512
;   r4 = ptr_A (current address of A[i])
;   r5 = ptr_B (current address of B[i])
;   r6 = tmp: A[i]
;   r7 = tmp: B[i]
;   r8 = product: A[i] * B[i]

    addi r1, r0, 0      ; sum = 0
    addi r4, r0, 0      ; ptr_A = 0
    addi r5, r0, 512    ; ptr_B = 512
    addi r2, r0, 256    ; loop counter = 256 (2 elements per iter)

loop:
    ld   r6, 0(r4)      ; A[i]
    ld   r7, 0(r5)      ; B[i]
    ld   r8, 1(r4)      ; A[i+1]
    ld   r9, 1(r5)      ; B[i+1]
    mac  r1, r6, r7     ; sum += A[i]*B[i]
    mac  r1, r8, r9     ; sum += A[i+1]*B[i+1]
    addi r4, r4, 2      ; ptr_A += 2
    addi r5, r5, 2      ; ptr_B += 2
    addi r2, r2, -1     ; i += 2
    bne  r2, r0, loop   ; repeat if not done
    halt
