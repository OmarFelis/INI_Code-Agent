import json

def clean_file():
    input_file = 'c:/INI_Code-Agent/data/outputJAVA.txt'
    output_file = 'c:/INI_Code-Agent/data/outputJAVA_clean.json'
    
    with open(input_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    cleaned_lines = []
    for line in lines:
        if line.startswith('@@'):
            continue
        if line.startswith('+'):
            cleaned_lines.append(line[1:])
        else:
            cleaned_lines.append(line)
            
    try:
        data = json.loads("".join(cleaned_lines))
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        print("JSON cleaned successfully")
    except Exception as e:
        print(f"Error parsing JSON: {e}")

if __name__ == '__main__':
    clean_file()
