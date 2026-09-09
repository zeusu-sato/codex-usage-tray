// CI-only native metadata server. Never distributed and never calls an account.
#import <Foundation/Foundation.h>
static void emit(id value) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:value options:0 error:nil];
    fwrite(data.bytes, 1, data.length, stdout); fputc('\n', stdout); fflush(stdout);
}
static void capture(id value) {
    NSString *path = NSProcessInfo.processInfo.environment[@"TRAY_FIXTURE_CAPTURE"];
    NSData *data = [NSJSONSerialization dataWithJSONObject:value options:0 error:nil];
    NSFileHandle *handle = [NSFileHandle fileHandleForWritingAtPath:path];
    [handle seekToEndOfFile]; [handle writeData:data]; [handle writeData:[@"\n" dataUsingEncoding:NSUTF8StringEncoding]]; [handle closeFile];
}
static NSString *reset(double seconds) {
    NSISO8601DateFormatter *format = [NSISO8601DateFormatter new];
    return [format stringFromDate:[NSDate dateWithTimeIntervalSinceNow:seconds]];
}
int main(int argc, const char *argv[]) { @autoreleasepool {
    BOOL claude = [[NSString stringWithUTF8String:argv[0]].lastPathComponent isEqual:@"claude"];
    NSArray *arguments = [NSProcessInfo.processInfo.arguments subarrayWithRange:NSMakeRange(1, argc-1)];
    if ([arguments isEqual:@[@"--version"]]) {
        NSString *version = NSProcessInfo.processInfo.environment[@"TRAY_FIXTURE_VERSION"] ?: @"2.1.263";
        puts(claude ? [[version stringByAppendingString:@" (Claude Code)"] UTF8String] : "codex-cli fixture-1.0"); return 0;
    }
    NSArray *expected = claude ? @[@"--print", @"--input-format", @"stream-json", @"--output-format", @"stream-json", @"--verbose", @"--safe-mode", @"--no-session-persistence", @"--strict-mcp-config", @"--no-chrome", @"--disable-slash-commands", @"--tools", @"", @"--setting-sources="] : @[@"app-server", @"--listen", @"stdio://"];
    if (![arguments isEqual:expected]) return 91;
    char *line = NULL; size_t size = 0;
    while (getline(&line, &size, stdin) > 0) {
        NSData *data = [[NSString stringWithUTF8String:line] dataUsingEncoding:NSUTF8StringEncoding];
        NSDictionary *message = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
        if (!message) return 92;
        capture(message);
        if (claude) {
            if (![message[@"type"] isEqual:@"control_request"]) return 93;
            NSString *subtype = message[@"request"][@"subtype"];
            id payload;
            if ([subtype isEqual:@"initialize"]) payload = @{@"account": @{@"email": @"private-fixture@example.invalid", @"organization": @"fixture-private-organization", @"apiProvider": @"firstParty", @"tokenSource": @"claude.ai"}};
            else if ([subtype isEqual:@"get_usage"] && [message[@"request"][@"skip_behaviors"] isEqual:@YES]) {
                payload = @{@"rate_limits_available": @YES, @"rate_limits": @{@"five_hour": @{@"utilization": @12, @"resets_at": reset(14400)}, @"seven_day": @{@"utilization": @27, @"resets_at": reset(172800)}, @"seven_day_sonnet": @{@"utilization": @99, @"resets_at": reset(172800)}}};
            } else return 94;
            emit(@{@"type": @"control_response", @"response": @{@"subtype": @"success", @"request_id": message[@"request_id"], @"response": payload}});
            if ([subtype isEqual:@"get_usage"]) break;
        } else {
            NSString *method = message[@"method"];
            if ([method isEqual:@"initialize"]) emit(@{@"id": message[@"id"], @"result": @{}});
            else if ([method isEqual:@"initialized"]) continue;
            else if ([method isEqual:@"account/rateLimits/read"]) {
                emit(@{@"id": message[@"id"], @"result": @{@"rateLimitsByLimitId": @{@"codex": @{@"limitId": @"codex", @"primary": @{@"usedPercent": @26, @"windowDurationMins": @10080, @"resetsAt": @((long)[NSDate dateWithTimeIntervalSinceNow:172800].timeIntervalSince1970)}}}}}); break;
            } else return 95;
        }
    }
    free(line); return 0;
} }
