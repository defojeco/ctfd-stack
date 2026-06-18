// CTFd 3.8.5 сериализует форму обновления через $(form).serializeJSON(true)
// и шлёт PATCH /api/v1/challenges/:id. Скрытое поле name="flagchoose"
// попадает в payload автоматически. Логика редактора — в update.html.
CTFd.plugin.run((_CTFd) => {
    const $ = _CTFd.lib.$;
    if (typeof window.mcBuildFieldUpdate === 'function') {
        window.mcBuildFieldUpdate();
    }
});
