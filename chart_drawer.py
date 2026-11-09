import io
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

def generate_chart(df: pd.DataFrame, analysis: dict):
    try:
        if df is None or df.empty:
            return None

        # إنشاء الرسم البياني المالي بدقة عالية
        fig, ax = plt.subplots(figsize=(10, 6), dpi=100)
        
        # رسم حركة السعر الحقيقية على فريم 144 دقيقة
        ax.plot(df.index, df['Close'], label='ICB Price (144m)', color='#1f77b4', linewidth=2)
        
        # استخراج المستويات من التحليل
        entry = analysis.get('entry')
        sl = analysis.get('sl')
        tp = analysis.get('tp')
        bias = analysis.get('bias', 'Neutral')
        
        # رسم خطوط المستويات المؤسسية لو متوفرة
        if entry:
            ax.axhline(y=entry, color='blue', linestyle='--', label=f'Entry: {entry}')
        if sl:
            ax.axhline(y=sl, color='red', linestyle=':', label=f'SL: {sl}')
        if tp:
            ax.axhline(y=tp, color='green', linestyle=':', label=f'TP: {tp}')
            
        ax.set_title(f'ICB Framework - 144m Live Chart | Bias: {bias}', fontsize=12, fontweight='bold', color='#333333')
        ax.grid(True, linestyle='--', alpha=0.5)
        ax.legend(loc='upper left', fontsize=9)
        
        plt.tight_layout()
        
        # حفظ الشارت في ذاكرة البايثون لإرساله مباشرة لتليجرام
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        plt.close(fig)
        
        return buf
    except Exception as e:
        print(f"Error generating chart: {e}")
        return None
