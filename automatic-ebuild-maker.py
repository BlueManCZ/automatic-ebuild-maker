#!/usr/bin/env python3

from datetime import date
from glob import glob
from json import load
from optparse import OptionParser
from signal import signal, SIGINT

import os
import sys
import tarfile
import unix_ar
import wget


class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def verbose_print(string):
    """Print function that prints only if --verbose flag is present."""
    if options.verbose:
        print(string)


def print_warning(string):
    """Print function that prints in Colors.WARNING colors."""
    print(Colors.WARNING + string + Colors.ENDC)


def print_bold(string):
    """Print function that prints bold text."""
    print(Colors.BOLD + string + Colors.ENDC)


def quit_handler(_, __):
    """Handler for exit signal."""
    print('\nSIGINT or CTRL-C detected. Exiting')
    quit()


if __name__ == '__main__':

    signal(SIGINT, quit_handler)

    parser = OptionParser()

    parser.add_option('', '--disable-system-ffmpeg',
                      action='store_true', dest='disable_system_ffmpeg', default=False,
                      help='don\'t include system-ffmpeg USE flag to the ebuild')
    parser.add_option('-v', '--verbose',
                      action='store_true', dest='verbose', default=False,
                      help='run script in verbose mode')
    parser.add_option('-u', '--url', dest='url',
                      help='specify input package file url',
                      metavar='<package>')

    parser.add_option('', '--amd64',  action='store_true', dest='amd64',
                      default=False, help='package is available as amd64 <arch>')
    parser.add_option('', '--i386', action='store_true', dest='i386',
                      default=False, help='package is available as i386 <arch>')

    (options, args) = parser.parse_args()

    # Set constant variables

    REAL_PATH = os.path.dirname(os.path.realpath(__file__))
    CACHE_DIR = '/tmp/automatic-ebuild-maker-cache/'
    DATABASE_FILE = REAL_PATH + '/database.json'

    if not options.url:
        print_warning('Input file not specifed. Please, use --input flag.')
        quit()

    if 'http://' not in options.url and 'https://' not in options.url:
        print('Wrong input %s' % options.url)
        print_warning('Input file has to be specifed by URL adress.')
        quit()

    suffix = options.url.split('.')[-1]

    architectures = []
    if options.amd64:
        architectures.append('amd64')
    if options.i386:
        architectures.append('i386')

    # if os.path.isfile(options.input_specified):
    #     verbose_print('[ok] Specified input file found:')
    #     verbose_print('   - %s\n' % options.input_specified)
    # else:
    #     print_warning('[error] Specified input file %s not found.' % options.input_specified)
    #     quit()

    if suffix == 'deb':
        if not os.path.isdir(CACHE_DIR):
            try:
                os.mkdir(CACHE_DIR)
            except OSError:
                print_warning('[error] Creation of the directory failed!')
                print('   -', CACHE_DIR)
                quit()

        src_uri = {}

        if '@ARCH@' in options.url:
            if architectures:
                for arch in architectures:
                    src_uri[arch] = options.url.replace('@ARCH@', arch)
                options.url = src_uri[architectures[0]]
            else:
                print_warning('[error] You have to provide at least one architecture when using @ARCH@ in url')
                quit()

        print(src_uri)

        target = options.url.split("/")[-1]
        filename = CACHE_DIR + target

        if os.path.isfile(filename):
            verbose_print('\nFile already downloaded in cache.')
        else:
            print_bold(f'\nDownloading target file to {filename}\n')
            print(f'{options.url}\n')
            wget.download(options.url, filename)
            print()

        dirname = filename.split('/')[-1].replace('.', '-')

        ar_file = unix_ar.open(filename)

        print()
        for file in ['control.tar.gz', 'data.tar.xz']:
            print(f'Extracting {file}', end=' ')
            sys.stdout.flush()
            name = file.split(".")[0]
            if os.path.isdir(f'{CACHE_DIR}{dirname}/{name}'):
                print('[already extracted]')
            else:
                status = ''
                for info in ar_file.infolist():
                    if info.name.decode('utf-8') in [f'{file}', f'{file}/']:
                        tarball = ar_file.open(info.name.decode('utf-8'))
                        tar_file = tarfile.open(fileobj=tarball)
                        tar_file.extractall(f'{CACHE_DIR}{dirname}/{name}')
                        print('[done]')
                        status = 'ok'
                        break

                if not status:
                    print_warning('[failed]')
                    quit()

        data = {}
        with open(CACHE_DIR + dirname + '/control/control') as file:
            line = file.readline()
            while line:
                key, value = line.split(': ', 1)
                description = []
                if key == 'Description':
                    description.append(value.replace('\n', ''))
                    description += file.readlines()
                    data[key] = description
                else:
                    data[key] = value.replace('\n', '')

                line = file.readline()

        warnings = []
        dependencies = []
        dependencies_string = ''

        # Find unnecessary files and replace them with dependencies
        use_dependencies = {}
        use_rm_files = {}

        swiftshader = glob(f'{CACHE_DIR}{dirname}/data/**/libEGL.so', recursive=True)
        swiftshader += glob(f'{CACHE_DIR}{dirname}/data/**/libGLESv2.so', recursive=True)
        swiftshader += glob(f'{CACHE_DIR}{dirname}/data/**/libvk_swiftshader.so', recursive=True)
        swiftshader += glob(f'{CACHE_DIR}{dirname}/data/**/libvulkan.so', recursive=True)

        ffmpeg = []
        if not options.disable_system_ffmpeg:
            ffmpeg = glob(f'{CACHE_DIR}{dirname}/data/**/libffmpeg.so', recursive=True)

        desktop = glob(f'{CACHE_DIR}{dirname}/data/**/*.desktop', recursive=True)

        pkg_postinst = []
        pkg_postrm = []

        if desktop:
            pkg_postinst.append('xdg_icon_cache_update')
            pkg_postinst.append('xdg_desktop_database_update')
            pkg_postrm.append('xdg_desktop_database_update')

        for d in desktop:
            with open(d) as file:
                content = file.read()
                if 'MimeType' in content:
                    pkg_postinst.append('xdg_mimeinfo_database_update')
                    pkg_postrm.append('xdg_mimeinfo_database_update')

        doc = glob(f'{CACHE_DIR}{dirname}/data/**/doc/*', recursive=True)

        doc_files = []

        for d in doc:
            doc_files.append(d.replace(f'{CACHE_DIR}{dirname}/data/', ''))

        doc_archives = []
        for d in doc:
            doc_archives += glob(f'{d}/**/*.gz', recursive=True)

        doc_archives_short = []
        for doc in doc_archives:
            doc_archives_short.append(doc.replace(f'{CACHE_DIR}{dirname}/data/', ''))

        print(doc_archives_short)

        executable_tmp = glob(f'{CACHE_DIR}{dirname}/data/**/{data["Package"]}', recursive=True)
        executable_tmp += glob(f'{CACHE_DIR}{dirname}/data/**/{data["Package"].capitalize()}', recursive=True)
        native_bin = ''

        for exe in executable_tmp:
            if 'usr' in exe and 'bin' in exe:
                native_bin = exe

        executable = []

        for exe in executable_tmp:
            skip = False
            for exe2 in executable_tmp:
                if (exe in exe2 and exe != exe2) or ('/opt/' not in exe
                                                     and f'/usr/share/{data["Package"]}' not in exe
                                                     and f'/usr/share/{data["Package"].capitalize()}' not in exe):
                    skip = True
                    break
            if skip:
                continue
            executable.append(exe.replace(f'{CACHE_DIR}{dirname}/data', ''))

        location = glob(f'{CACHE_DIR}{dirname}/data/opt')
        if not location:
            location = glob(f'{CACHE_DIR}{dirname}/data/usr')
        if location:
            location = location[0].replace(f'{CACHE_DIR}{dirname}/data', '')

        root_folders_tmp = glob(f'{CACHE_DIR}{dirname}/data/*')
        root_folders = []

        for folder in root_folders_tmp:
            root_folders.append(folder.replace(f'{CACHE_DIR}{dirname}/data/', ''))

        trash = {'system-mesa': swiftshader, 'system-ffmpeg': ffmpeg}
        trash_keys = list(trash.keys())
        trash_keys.sort()

        use_flags = []

        if os.path.isfile(DATABASE_FILE):
            if 'Homepage' not in data:
                data['Homepage'] = ''
                warnings.append('Homepage is missing.')

            if 'License' in data:
                if data['License'] in ['', 'unknown']:
                    warnings.append(f'License is currently set to \"{data["License"]}\".')
            else:
                data['License'] = ''
                warnings.append('License is missing.')

            verbose_print('\n[ok] Found database file:')
            verbose_print('   - %s\n' % DATABASE_FILE)
            with open(DATABASE_FILE) as json_file:
                database = load(json_file)

            # Get dependencies from .deb control file
            deb_dependencies = []
            if 'Depends' in data:
                deb_dependencies += data['Depends'].split(', ')
            if 'Suggests' in data:
                deb_dependencies += data['Suggests'].split(', ')

            for d in deb_dependencies:
                if '|' in d:
                    status = ''
                    for dd in d.split(' | '):
                        if dd in database['dependencies-optional']:
                            use_flags.append(database['dependencies-optional'][dd])
                            status = 'ok'
                        elif dd in database['dependencies']:
                            if database['dependencies'][dd] not in dependencies:
                                dependencies.append(database['dependencies'][dd])
                                status = 'ok'
                    if not status:
                        warnings.append(f'Gentoo alternative dependency for \"{d}\" not found in database.json.')

                elif d in database['dependencies-optional']:
                    use_flags.append(database['dependencies-optional'][d])

                elif d in database['dependencies']:
                    if database['dependencies'][d] not in dependencies:
                        dependencies.append(database['dependencies'][d])

                else:
                    warnings.append(f'Gentoo alternative dependency for \"{d}\" not found in database.json.')

            dependencies.sort()

            counter = 0
            for d in dependencies:
                if counter == 0:
                    if len(dependencies) == 1:
                        dependencies_string += f'{d}'
                    else:
                        dependencies_string += f'{d}\n'
                elif counter == len(dependencies) - 1:
                    dependencies_string += f'\t{d}'
                else:
                    dependencies_string += f'\t{d}\n'
                counter += 1

            for use in trash_keys:
                if trash[use]:
                    trash[use].sort()
                    use_dependencies[use] = database['use-dependencies'][use]
                    use_rm_files[use] = []
                    for path in trash[use]:
                        use_rm_files[use].append(path.replace(f'{CACHE_DIR}{dirname}/data/', ''))

        else:
            print_warning('[warning] database file %s not found.' % DATABASE_FILE)

        version = data['Version'].split('-')[0]
        description = data['Description'][0] if data['Description'][0] else data['Description'][1]
        description = description.replace('\n', '')

        for i in range(0, len(description)):
            if description[i] != ' ':
                description = description[i:]
                break

        use_flags += list(use_dependencies.keys())

        if doc:
            use_flags.append('doc')

        use_flags.sort()

        keys = list(use_dependencies.keys())
        keys.sort()

        for use in use_flags:
            if use in database['use-dependencies']:
                dependencies_string += f'\n\t{use}? ( {database["use-dependencies"][use]} )'

        architectures_tmp = architectures
        architectures = []
        for arch in architectures_tmp:
            if arch == 'i386' or args == 'i686':
                architectures.append('x86')
            else:
                architectures.append(arch)

        if architectures:
            keywords = f'~{" ~".join(architectures)}'
        else:
            keywords = f'~{data["Architecture"]}'

        pv = '${PV}'
        url = options.url.replace(version, pv)

        counter = 0
        if src_uri:
            src_uri_string = ''
            for arch in src_uri:
                url = src_uri[arch].replace(version, pv)
                keyword = arch
                if keyword == 'i386' or keyword == 'i686':
                    keyword = 'x86'
                if counter == 0:
                    if len(src_uri) == 1:
                        src_uri_string = f'{keyword} -> {data["Package"]}-{pv}.{suffix}'
                    else:
                        src_uri_string += f'{keyword}? ( {url} -> {data["Package"]}-{pv}-{arch}.{suffix} )\n'
                elif counter == len(src_uri) - 1:
                    src_uri_string += f'\t{keyword}? ( {url} -> {data["Package"]}-{pv}-{arch}.{suffix} )'
                else:
                    src_uri_string += f'\t{keyword}? ( {url} -> {data["Package"]}-{pv}-{arch}.{suffix} )\n'
                counter += 1
        else:
            src_uri_string = f'{url} -> {data["Package"]}-{pv}.{suffix}'

        file = open(f'{data["Package"]}-{version}.ebuild', 'w')
        file.writelines([
            f'# Copyright 1999-{date.today().year} Gentoo Authors\n'
            '# Distributed under the terms of the GNU General Public License v2\n\n'
            '# File was automatically generated by automatic-ebuild-maker\n\n'
            'EAPI=7\n'
            'inherit desktop unpacker xdg-utils\n\n'
            f'DESCRIPTION="{description}"\n'
            f'HOMEPAGE=\"{data["Homepage"]}\"\n'
            f'SRC_URI=\"{src_uri_string}\"\n\n'
            f'LICENSE=\"{data["License"]}\"\n'
            'SLOT=\"0\"\n'
            f'KEYWORDS=\"{keywords}\"\n'
            f'IUSE=\"{" ".join(use_flags)}\"\n\n'
            f'RDEPEND=\"{dependencies_string}\"\n\n'
            'QA_PREBUILT="*"\n\n'
            'S="${WORKDIR}"\n\n'
        ])

        # src_prepare()

        if use_rm_files or doc_archives_short:
            file.write('src_prepare() {\n')
            if use_rm_files:
                for use in use_rm_files:
                    file.write(f'\tif use {use} ; then\n')
                    for f in use_rm_files[use]:
                        file.write(f'\t\trm -f "{f}" || die "rm failed"\n')
                    file.write('\tfi\n\n')
            if doc_archives_short:
                for doc in doc_archives_short:
                    file.write(f'\tunpack "{doc}" || die "unpack failed"\n')
                    file.write(f'\trm -f "{doc}" || die "rm failed"\n')
                    extracted_location = ".".join(doc.split("/")[-1].split(".")[:-1])
                    target_location = "/".join(doc.split("/")[:-1])
                    file.write(f'\tmv "{extracted_location}" "{target_location}"\n')
                file.write('\n')
            file.write('\tdefault\n}\n\n')

        # src_install()

        file.write('src_install() {\n')

        # file.write(f'\tinsinto "{location}"\n')
        file.write('\tcp -a . "${ED}" || die "cp failed"\n\n')

        for doc in doc_files:
            ed = "${ED}"
            file.write(f'\trm -r "{ed}/{doc}" || die "rm failed"\n')

        if doc_files:
            file.write('\n\tif use doc ; then\n')
            for doc in doc_files:
                file.write(f'\t\tdodoc -r "{doc}" || die "dodoc failed"\n')
            file.write('\tfi\n')

        if use_rm_files:
            for use in use_rm_files:
                if use in database["use-symlinks"]:
                    file.write(f'\n\tif use {use} ; then\n')
                    for f in use_rm_files[use]:
                        file.write(f'\t\tdosym \"{database["use-symlinks"][use]}\" \"/{f}\" || die "dosym failed"\n')
            file.write('\tfi\n')

        if not native_bin:
            file.write('\n')
            for exe in executable:
                file.write(f'\tdosym "{exe}" "/usr/bin/{data["Package"]}" || die "dosym failed"\n')

        file.write('}\n\n')

        # pkg_postinst()

        if pkg_postinst:
            file.write('pkg_postinst() {\n')
            for command in pkg_postinst:
                file.write(f'\t{command}\n')
            file.write('}\n\n')

        # pkg_postrm()

        if pkg_postrm:
            file.write('pkg_postrm() {\n')
            for command in pkg_postrm:
                file.write(f'\t{command}\n')
            file.write('}\n')

        file.close()

        print_bold(f'File {data["Package"]}-{version}.ebuild created.')

        if warnings:
            print_warning('\nThings that may require your attention:\n')
            for warning in warnings:
                print_bold(warning)

        file = open(f'{data["Package"]}-metadata.xml', 'w')
        file.writelines([
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE pkgmetadata SYSTEM "http://www.gentoo.org/dtd/metadata.dtd">\n'
            '<pkgmetadata>\n'
        ])

        if description:
            file.write(f'\t<longdescription>\n\t\t{description}\n\t</longdescription>\n')

        if use_flags:
            file.write('\t<use>\n')
            for use in use_flags:
                if use in database['use-descriptions']:
                    file.write(f'\t\t<flag name="{use}">{database["use-descriptions"][use]}</flag>\n')
            file.write('\t</use>\n')

        file.write('</pkgmetadata>\n')
        print(use_flags)
