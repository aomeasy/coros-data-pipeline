with open('docs/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the problematic line 301 in the main script block
lines = content.split('\n')

# Find line with respiratory_rate and spo2 (the problematic one)
for i, line in enumerate(lines):
    if 'respiratory_rate' in line and 'spo2' in line and 'html +=' in line:
        print(f'Found at line {i+1}')
        # Replace with safe string concatenation using DOM-free approach
        lines[i] = """    html += '<tr><td>' + b.date + '</td><td>' + (b.respiratory_rate ? b.respiratory_rate.value : '-') + ' ' + (b.respiratory_rate ? b.respiratory_rate.unit : '') + '</td><td><span class="badge ' + (b.respiratory_rate && b.respiratory_rate.status === 'normal' ? 'badge-success' : b.respiratory_rate && b.respiratory_rate.status === 'excellent' ? 'badge-info' : 'badge-warning') + '">' + (b.respiratory_rate ? b.respiratory_rate.description : '-') + '</span></td><td>' + (b.spo2 ? b.spo2.avg : '-') + '%</td><td><span class="badge ' + (b.spo2 && b.spo2.status === 'normal' ? 'badge-success' : 'badge-warning') + '">' + (b.spo2 ? b.spo2.description : '-') + '</span></td></tr>';"""
        break

new_content = '\n'.join(lines)

with open('docs/index.html', 'w', encoding='utf-8') as f:
    f.write(new_content)

print('Fixed!')
