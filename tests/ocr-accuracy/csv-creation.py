import csv

samples = [
    (1, '179', 'CE61WYL', 79.0),
    (2, '88', 'DA07CLX', 80.9),
    (3, '69', 'AF65JKV', 99.2),
    (4, '92', 'EY09VWS', 99.1),
    (5, '78', 'GJ06EPD', 92.9),
    (6, '171', 'HX52BPF', 67.9),
    (7, '171', 'HX52BPF', 44.7),
    (8, '7', 'EY61NBG', 83.5),
    (9, '7', 'EY61NBG', 90.6),
    (10, '32', 'AK64DMV', 99.9),
    (11, '82', 'LN15ZZC', 82.6),
    (12, '82', 'LN15ZZC', 82.0),
    (13, '92', 'EY09VWS', 66.2),
    (14, '139', 'NL64OGX', 95.8),
    (15, '149', 'LP14LJA', 41.2),
    (16, '179', 'CE61WYL', 74.9),
    (17, '1', 'WR02FKD', 96.2),
    (18, '1', 'WR02FKD', 95.9),
    (19, '144', 'LL61PZS', 84.3),
    (20, '112', 'BP63LYH', 95.9),
    (21, '179', 'CE61WYL', 60.6),
    (22, '136', 'WG65ZFX', 99.6),
    (23, '22', 'HN14CDY', 68.5),
    (24, '144', 'LL61PZS', 81.5),
    (25, '69', 'AF65JKV', 99.6),
]

with open('validation_results.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['#', 'Car_ID', 'OCR_Result', 'Confidence_%', 'Actual_Plate', 'Match', 'Notes'])

    for sample in samples:
        writer.writerow([sample[0], sample[1], sample[2], sample[3], '', '', ''])

print("Created validation_results.csv")
print("\nNext steps:")
print("1. Open validation_images/ folder")
print("2. For each image, look at the actual license plate")
print("3. Fill in 'Actual_Plate' column in validation_results.csv")
print("4. Mark 'Match' as YES, NO, or PARTIAL")
print("5. Add notes for any interesting cases")
