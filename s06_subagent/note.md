# s06_subagent

```
主 Agent：
    task("查找登录代码，并总结调用流程")
        ↓
    Python 进入 run_subagent()
        ↓
    子 Agent：glob("**/*auth*")
        ↓
    子 Agent：read_file("auth.py")
        ↓
    子 Agent：返回“登录入口是……调用流程是……”
        ↓
    run_subagent() 返回这段文字
        ↓
主 Agent：
    收到 task 的工具结果，继续处理原始任务
```