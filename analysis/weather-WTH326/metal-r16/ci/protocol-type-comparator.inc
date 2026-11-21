static void skipQuoted(const char *&p) {
    if (*p != '"') return;
    ++p;
    while (*p && *p != '"') { if (*p == '\\' && p[1]) ++p; ++p; }
    if (*p != '"') throw std::runtime_error("unterminated quoted ABI name");
    ++p;
}

static std::string canonicalType(const char *&p) {
    while (*p && strchr("rnNoORVA", *p)) ++p;
    if (!*p) throw std::runtime_error("missing ABI type");
    const char kind = *p++;
    std::string out(1, kind);
    if (kind == '@') {
        if (*p == '?') { out += *p++; }
        else if (*p == '"') skipQuoted(p);
    } else if (kind == '^') {
        out += canonicalType(p);
    } else if (kind == '{' || kind == '(') {
        const char end = kind == '{' ? '}' : ')';
        while (*p && *p != '=' && *p != end) ++p; // Struct names are not ABI.
        if (*p == '=') {
            ++p;
            while (*p && *p != end) {
                if (*p == '"') skipQuoted(p); // Optional field names.
                else out += canonicalType(p);
            }
        }
        if (*p != end) throw std::runtime_error("unterminated aggregate ABI");
        out += *p++;
    } else if (kind == '[') {
        while (*p >= '0' && *p <= '9') out += *p++;
        out += canonicalType(p);
        if (*p != ']') throw std::runtime_error("unterminated array ABI");
        out += *p++;
    } else if (kind == 'b') {
        while (*p >= '0' && *p <= '9') out += *p++;
    } else if (!strchr("cislqCISLQfdDBv*#:?", kind)) {
        throw std::runtime_error("unsupported ABI token " + std::string(1, kind));
    }
    return out;
}

static NSDictionary *describeType(const char *type) {
    const char *cursor = type;
    const std::string canonical = canonicalType(cursor);
    if (*cursor) throw std::runtime_error("unconsumed ABI type text");
    NSUInteger size = 0, alignment = 0;
    if (canonical != "v") NSGetSizeAndAlignment(type, &size, &alignment);
    return @{@"raw": [NSString stringWithUTF8String:type],
        @"canonical": [NSString stringWithUTF8String:canonical.c_str()],
        @"bytes": @(size), @"alignment": @(alignment)};
}

static NSDictionary *describeSignature(const char *encoding) {
    NSMethodSignature *signature = [NSMethodSignature signatureWithObjCTypes:encoding];
    if (!signature) throw std::runtime_error("NSMethodSignature rejected encoding");
    NSMutableArray *arguments = [NSMutableArray array];
    for (NSUInteger i = 0; i < signature.numberOfArguments; ++i)
        [arguments addObject:describeType([signature getArgumentTypeAtIndex:i])];
    return @{@"return": describeType(signature.methodReturnType),
        @"return_bytes": @(signature.methodReturnLength), @"arguments": arguments};
}

static bool typesEqual(NSDictionary *a, NSDictionary *b) {
    return [a[@"canonical"] isEqual:b[@"canonical"]] &&
        [a[@"bytes"] isEqual:b[@"bytes"]] && [a[@"alignment"] isEqual:b[@"alignment"]];
}

static bool signaturesEqual(NSDictionary *a, NSDictionary *b) {
    if (!typesEqual(a[@"return"], b[@"return"]) || ![a[@"return_bytes"] isEqual:b[@"return_bytes"]]) return false;
    NSArray *aa = a[@"arguments"], *bb = b[@"arguments"];
    if (aa.count != bb.count) return false;
    for (NSUInteger i = 0; i < aa.count; ++i) if (!typesEqual(aa[i], bb[i])) return false;
    return true;
}

