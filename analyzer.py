
async def send_analysis(update, context, user_symbol):
    message = update.effective_message

    resolved = resolve_symbol(user_symbol)

    if not resolved:
        await message.reply_text(
            "الرمز غير موجود في ملفات الرموز الحالية.\n\n"
            "راجع symbols/forex.json أو symbols/crypto.json."
        )
        return

    await context.bot.send_chat_action(
        chat_id=message.chat_id,
        action=ChatAction.TYPING
    )

    status_message = await message.reply_text(
        f"⏳ جاري جمع بيانات {user_symbol} وتحليل الأطر الزمنية..."
    )

    try:
        bundle, analysis = await run_analysis(resolved)

        report = build_report(user_symbol, analysis)

        await status_message.edit_text(
            "🧠 تم التحليل الحسابي.\n"
            "⏳ جاري تشغيل عقل ICB وربط نتائج Groq..."
        )

        ai_report = await asyncio.to_thread(
            interpret_analysis,
            user_symbol,
            analysis
        )

        ai_section = (
            "\n\n━━━━━━━━━━━━━━━━━━\n"
            "🧠 <b>ICB AI INTERPRETATION</b>\n\n"
            + escape(str(ai_report))
        )

        available_length = MAX_REPORT_LENGTH - len(ai_section)

        if available_length < 100:
            ai_section = (
                "\n\n━━━━━━━━━━━━━━━━━━\n"
                "🧠 <b>ICB AI INTERPRETATION</b>\n\n"
                + escape(str(ai_report)[:1200])
            )
            available_length = MAX_REPORT_LENGTH - len(ai_section)

        if len(report) > available_length:
            report = report[:max(0, available_length - 30)]
            report += "\n\n<i>تم اختصار التقرير للحفاظ على طول الرسالة.</i>"

        final_report = report + ai_section

        await status_message.edit_text(
            final_report,
            parse_mode="HTML"
        )

        try:
            chart = await asyncio.to_thread(
                generate_timeframe_chart,
                bundle,
                analysis,
                user_symbol
            )

            if chart:
                if hasattr(chart, "seek"):
                    chart.seek(0)

                await message.reply_photo(
                    photo=chart,
                    caption=f"ICB | {user_symbol} | Market Structure"
                )

        except Exception:
            logger.exception("Chart generation failed")

    except Exception as error:
        logger.exception(
            "Analysis failed for %s",
            user_symbol
        )

        await status_message.edit_text(
            "❌ تعذر إكمال التحليل.\n\n"
            f"التفاصيل: {escape(str(error)[:700])}\n\n"
            "راجع سجلات Railway لمعرفة مصدر المشكلة.",
            parse_mode="HTML"
        )
