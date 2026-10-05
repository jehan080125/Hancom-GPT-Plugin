def choose_file():
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True)
    try:
        return filedialog.askopenfilename(parent=root, title='작성할 한글 파일 선택', filetypes=[('한글 문서', '*.hwp *.hwpx')]) or None
    finally: root.destroy()

def choose_bookmark(names):
    import tkinter as tk
    root = tk.Tk(); root.title('입력할 책갈피 선택'); root.geometry('420x360'); root.attributes('-topmost', True)
    result = []
    tk.Label(root, text='사용자가 문서에 만든 책갈피를 선택하세요.').pack(pady=10)
    listing = tk.Listbox(root, exportselection=False)
    listing.pack(fill='both', expand=True, padx=12)
    for name in names: listing.insert('end', name)
    def accept(*_):
        if listing.curselection():
            result.append(listing.get(listing.curselection()[0])); root.destroy()
    tk.Button(root, text='선택', command=accept).pack(pady=10)
    listing.bind('<Double-Button-1>', accept)
    root.mainloop()
    return result[0] if result else None

def choose_open_document(documents):
    import tkinter as tk
    root = tk.Tk(); root.title('열린 한글 문서 선택'); root.geometry('720x360'); root.attributes('-topmost', True)
    selected = []
    tk.Label(root, text='직접 작성할 열린 문서를 선택하세요. 저장은 직접 해야 합니다.').pack(pady=10)
    listing = tk.Listbox(root, exportselection=False)
    listing.pack(fill='both', expand=True, padx=12)
    for d in documents:
        listing.insert('end', f"{d['title']} {'(저장 전 변경 있음)' if d['modified'] else ''} — {d['file'] or '새 문서'}")
    def accept(*_):
        if listing.curselection():
            selected.append(documents[listing.curselection()[0]]['window_id']); root.destroy()
    tk.Button(root, text='이 문서에 직접 작성', command=accept).pack(pady=10)
    listing.bind('<Double-Button-1>', accept)
    root.mainloop()
    return selected[0] if selected else None
