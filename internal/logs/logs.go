package logs

import (
	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"
)

var global *zap.SugaredLogger

func Init(development bool) error {
	var cfg zap.Config
	if development {
		cfg = zap.NewDevelopmentConfig()
	} else {
		cfg = zap.NewProductionConfig()
		cfg.Encoding = "console"
		cfg.EncoderConfig.EncodeTime = zapcore.ISO8601TimeEncoder
	}
	l, err := cfg.Build(zap.AddCallerSkip(1), zap.WithFatalHook(zapcore.WriteThenNoop), zap.AddStacktrace(zapcore.FatalLevel))
	if err != nil {
		return err
	}
	global = l.Sugar()
	return nil
}

func l() *zap.SugaredLogger {
	if global == nil {
		lg, _ := zap.NewDevelopment(zap.AddCallerSkip(1))
		global = lg.Sugar()
	}
	return global
}

func Info(msg string)                { l().Info(msg) }
func Infof(fmt string, args ...any)  { l().Infof(fmt, args...) }
func Debug(msg string)               { l().Debug(msg) }
func Debugf(fmt string, args ...any) { l().Debugf(fmt, args...) }
func Warn(msg string)                { l().Warn(msg) }
func Warnf(fmt string, args ...any)  { l().Warnf(fmt, args...) }
func Error(msg string)               { l().Error(msg) }
func Errorf(fmt string, args ...any) { l().Errorf(fmt, args...) }
